"""
CADtributions
-------------
A Fusion 360 add-in that tracks every time you save a new version of a
design (or create a brand new file) and shows them in a GitHub-style
"contribution graph" -- a CADtribution graph.

Author: Sri
"""

import adsk.core
import adsk.fusion
import adsk.cam
import traceback
import os
import json
import datetime
import pathlib
import threading

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------

_app: adsk.core.Application = None
_ui: adsk.core.UserInterface = None

# Fusion requires a reference to every event handler to be kept around for
# the lifetime of the add-in, otherwise Python garbage collects them and the
# events silently stop firing.
_handlers = []

ADDIN_NAME = 'CADtributions'
CMD_ID_SHOW_GRAPH = 'CADtributions_ShowGraph'
PALETTE_ID = 'CADtributions_Palette'
PALETTE_NAME = 'CADtributions'
DESCRIPTION_READY_EVENT_ID = 'CADtributions_DescriptionReady'

# How long to wait, in the background, before re-checking a version's
# description against the cloud. Not a hard guarantee, just a reasonable bet.
DESCRIPTION_RECHECK_DELAY_SECONDS = 3.0

ADDIN_FOLDER = os.path.dirname(os.path.realpath(__file__))
DATA_FILE_PATH = os.path.join(ADDIN_FOLDER, 'cadtributions_data.json')
HTML_FILE_PATH = os.path.join(ADDIN_FOLDER, 'palette.html')


# ---------------------------------------------------------------------------
# Data persistence
# ---------------------------------------------------------------------------
# Every "CADtribution" is stored as one JSON record:
#   {
#     "id":          unique id used to de-duplicate (fileId:version, or a
#                    local equivalent for files not saved to a Fusion project)
#     "timestamp":   full ISO-8601 timestamp of the save
#     "date":        YYYY-MM-DD (local date), used to bucket the graph
#     "project":     the Fusion "Data Panel" project name
#     "path":        breadcrumb path, e.g. "MyProject / Robots / Chassis"
#     "file":        the design's file name
#     "version":     the version number Fusion assigned to this save
#     "isNewFile":   True if this save created the file for the first time
#     "description": the version description, pulled from Fusion's own save
#                    dialog (may briefly show a placeholder right after a
#                    save, until the background recheck confirms it)
#     "fileId":      the Fusion Data Panel file id (URN), or null if this
#                    document isn't stored in a Fusion project
#   }

def load_data() -> list:
    """Load all recorded CADtributions from disk. Never raises."""
    if not os.path.exists(DATA_FILE_PATH):
        return []
    try:
        with open(DATA_FILE_PATH, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                return []
            return json.loads(content)
    except (json.JSONDecodeError, OSError):
        # Corrupt or unreadable file -- back it up rather than losing data
        # silently, and start fresh so the add-in keeps working.
        try:
            backup_path = DATA_FILE_PATH + '.bak'
            os.replace(DATA_FILE_PATH, backup_path)
        except OSError:
            pass
        return []


def save_data(entries: list) -> None:
    tmp_path = DATA_FILE_PATH + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(entries, f, indent=2)
    os.replace(tmp_path, DATA_FILE_PATH)


def add_entry(entry: dict) -> bool:
    """Append a new CADtribution if it isn't already recorded.

    Returns True if a new entry was actually added (so callers can decide
    whether to refresh the UI), False if it was a duplicate.
    """
    entries = load_data()
    if any(e.get('id') == entry['id'] for e in entries):
        return False
    entries.append(entry)
    save_data(entries)
    return True


def update_entry_description(entry_id: str, new_description: str) -> bool:
    """Find an existing entry by id and correct its description in place.

    Returns True if something was actually changed, so the caller can decide
    whether the palette needs refreshing.
    """
    entries = load_data()
    changed = False
    for e in entries:
        if e.get('id') == entry_id and e.get('description') != new_description:
            e['description'] = new_description
            changed = True
            break
    if changed:
        save_data(entries)
    return changed


# ---------------------------------------------------------------------------
# Helpers for reading information out of the Fusion document / data file
# ---------------------------------------------------------------------------

def get_full_breadcrumb(data_file: adsk.core.DataFile) -> str:
    """Build a human readable 'Project / Folder / Subfolder' path."""
    try:
        parts = []
        folder = data_file.parentFolder
        while folder is not None:
            parts.insert(0, folder.name)
            folder = folder.parentFolder

        project_name = None
        try:
            project_name = data_file.parentProject.name
        except Exception:
            pass

        # Avoid "Project / Project" when the root folder repeats the
        # project's name.
        if project_name and (not parts or parts[0] != project_name):
            parts.insert(0, project_name)

        return ' / '.join(parts) if parts else (project_name or '')
    except Exception:
        return ''


def build_entry_for_saved_document(doc: adsk.core.Document) -> dict:
    """Turn a just-saved Document into a CADtribution record. The
    description here is always the safe placeholder -- the real one (if
    different) arrives a few seconds later via the background recheck."""
    now = datetime.datetime.now()
    timestamp = now.isoformat(timespec='seconds')
    date_str = now.strftime('%Y-%m-%d')

    data_file = None
    try:
        data_file = doc.dataFile
    except Exception:
        data_file = None

    if data_file is not None:
        # Normal case: the document lives in a Fusion "Data Panel" project,
        # so Fusion is already tracking real version numbers for us.
        version = data_file.versionNumber
        entry_id = f'{data_file.id}:{version}'
        project_name = ''
        try:
            project_name = data_file.parentProject.name
        except Exception:
            project_name = 'Unknown Project'

        entry = {
            'id': entry_id,
            'timestamp': timestamp,
            'date': date_str,
            'project': project_name,
            'path': get_full_breadcrumb(data_file),
            'file': data_file.name,
            'version': version,
            'isNewFile': version == 1,
            'fileId': data_file.id,
            'description': f'Cadtributed in {data_file.name}',
        }
    else:
        # Fallback for documents that aren't saved into a Fusion project
        # (rare in normal use, but possible). There's no real version
        # number available from the API here, so we derive one from what
        # we've already recorded for this file name.
        file_name = doc.name or 'Untitled'
        local_key = f'local::{file_name}'
        existing = [e for e in load_data() if e.get('id', '').startswith(local_key + ':')]
        version = len(existing) + 1
        entry = {
            'id': f'{local_key}:{version}:{timestamp}',
            'timestamp': timestamp,
            'date': date_str,
            'project': 'Local (not in a Fusion project)',
            'path': file_name,
            'file': file_name,
            'version': version,
            'isNewFile': version == 1,
            'fileId': None,
            'description': f'Cadtributed in {file_name}',
        }

    return entry


def schedule_description_recheck(entry_id: str, file_id: str):
    """Runs on a background thread. Fires the CustomEvent a few times at
    increasing delays, since we don't know exactly how long Fusion's cloud
    sync takes -- each firing re-reads the description fresh and overwrites
    the entry, so a later, more-likely-correct check wins over an earlier,
    possibly-stale one."""
    def _poll_and_fire():
        import time
        # Gaps *between* checks, not total elapsed time -- this checks at
        # roughly +2s, +5s, and +10s after the save.
        gaps_between_checks = [2.0, 3.0, 5.0]
        for gap in gaps_between_checks:
            time.sleep(gap)
            try:
                payload = json.dumps({'entryId': entry_id, 'fileId': file_id})
                _app.fireCustomEvent(DESCRIPTION_READY_EVENT_ID, payload)
            except Exception:
                pass

    threading.Thread(target=_poll_and_fire, daemon=True).start()


# ---------------------------------------------------------------------------
# Palette (the CADtribution graph UI)
# ---------------------------------------------------------------------------

def get_palette() -> adsk.core.Palette:
    return _ui.palettes.itemById(PALETTE_ID)


def show_palette():
    palette = get_palette()
    if palette is None:
        html_uri = pathlib.Path(HTML_FILE_PATH).as_uri()
        palette = _ui.palettes.add(
            id=PALETTE_ID,
            name=PALETTE_NAME,
            htmlFileURL=html_uri,
            isVisible=True,
            showCloseButton=True,
            isResizable=True,
            width=920,
            height=680,
        )
        on_incoming = CADtributionsHTMLHandler()
        palette.incomingFromHTML.add(on_incoming)
        _handlers.append(on_incoming)

        on_closed = CADtributionsPaletteClosedHandler()
        palette.closed.add(on_closed)
        _handlers.append(on_closed)
    else:
        palette.isVisible = True

    send_data_to_palette()


def _current_payload() -> str:
    return json.dumps(load_data())


def send_data_to_palette():
    """Push the latest CADtribution history into the open palette, if any."""
    palette = get_palette()
    if palette is not None and palette.isVisible:
        palette.sendInfoToHTML('populate', _current_payload())


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

class DocumentSavedHandler(adsk.core.DocumentEventHandler):
    """Fires every time any document is saved -- this is where a
    CADtribution actually gets recorded."""

    def notify(self, args: adsk.core.DocumentEventArgs):
        try:
            doc = args.document
            entry = build_entry_for_saved_document(doc)

            added = add_entry(entry)
            if added:
                send_data_to_palette()

            if entry.get('fileId'):
                schedule_description_recheck(entry['id'], entry['fileId'])
        except Exception:
            # Never let a failure here interrupt the user's save.
            if _ui:
                _ui.messageBox(
                    'CADtributions failed to record a save:\n{}'.format(
                        traceback.format_exc()
                    )
                )


class DescriptionReadyHandler(adsk.core.CustomEventHandler):
    """Fires back on Fusion's main thread once the background recheck
    thread's delay has elapsed. Safe to touch Fusion API objects here."""

    def notify(self, args: adsk.core.CustomEventArgs):
        try:
            payload = json.loads(args.additionalInfo)
            entry_id = payload.get('entryId')
            file_id = payload.get('fileId')
            if not entry_id or not file_id:
                return

            data_file = _app.data.findFileById(file_id)
            if data_file is None:
                return

            try:
                data_file.refresh()
            except Exception:
                pass

            try:
                real_description = data_file.description
            except AttributeError:
                real_description = None

            if real_description:
                changed = update_entry_description(entry_id, real_description.strip())
                if changed:
                    send_data_to_palette()
        except Exception:
            if _ui:
                _ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))


class ShowGraphCommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    """Fires when the toolbar button is clicked."""

    def notify(self, args: adsk.core.CommandCreatedEventArgs):
        try:
            show_palette()
        except Exception:
            if _ui:
                _ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))


class CADtributionsHTMLHandler(adsk.core.HTMLEventHandler):
    """Fires when the palette's JavaScript calls adsk.fusionSendData(...)."""

    def notify(self, args):
        try:
            html_args = adsk.core.HTMLEventArgs.cast(args)
            action = html_args.action

            if action in ('ready', 'refresh'):
                html_args.returnData = _current_payload()

            elif action == 'openFile':
                incoming = json.loads(html_args.data) if html_args.data else {}
                file_id = incoming.get('fileId')
                if not file_id:
                    html_args.returnData = json.dumps({'status': 'no_id'})
                else:
                    try:
                        data_file = _app.data.findFileById(file_id)
                        if data_file is None:
                            if _ui:
                                _ui.messageBox(
                                    "This file couldn't be opened -- it may have been "
                                    "deleted or moved."
                                )
                            html_args.returnData = json.dumps({'status': 'not_found'})
                        else:
                            _app.documents.open(data_file, True)
                            palette = get_palette()
                            if palette is not None:
                                palette.isVisible = False
                                palette.isVisible = True
                            html_args.returnData = json.dumps({'status': 'OK'})
                    except Exception:
                        if _ui:
                            _ui.messageBox("This file couldn't be opened.")
                        html_args.returnData = json.dumps({'status': 'error'})

            else:
                html_args.returnData = json.dumps({'status': 'ignored'})
        except Exception:
            if _ui:
                _ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))


class CADtributionsPaletteClosedHandler(adsk.core.UserInterfaceGeneralEventHandler):
    def notify(self, args):
        pass


# ---------------------------------------------------------------------------
# Add-in lifecycle
# ---------------------------------------------------------------------------

def _initialize():
    cmd_def = _ui.commandDefinitions.itemById(CMD_ID_SHOW_GRAPH)
    if not cmd_def:
        cmd_def = _ui.commandDefinitions.addButtonDefinition(
            CMD_ID_SHOW_GRAPH,
            'CADtributions',
            'View your CADtributions graph with a GitHub-style view of your Fusion 360 save history: what you saved, where, and when.',
            './resources/graph_cmd',
        )

    on_created = ShowGraphCommandCreatedHandler()
    cmd_def.commandCreated.add(on_created)
    _handlers.append(on_created)

    workspace = _ui.workspaces.itemById('FusionSolidEnvironment')
    panel = workspace.toolbarPanels.itemById('SolidScriptsAddinsPanel')
    if panel.controls.itemById(CMD_ID_SHOW_GRAPH) is None:
        control = panel.controls.addCommand(cmd_def)
        control.isPromoted = False

    on_saved = DocumentSavedHandler()
    _app.documentSaved.add(on_saved)
    _handlers.append(on_saved)

    # Remove any leftover registration from a previous run before adding
    # our own, so restarting the add-in doesn't error out.
    try:
        _app.unregisterCustomEvent(DESCRIPTION_READY_EVENT_ID)
    except Exception:
        pass
    custom_event = _app.registerCustomEvent(DESCRIPTION_READY_EVENT_ID)
    on_description_ready = DescriptionReadyHandler()
    custom_event.add(on_description_ready)
    _handlers.append(on_description_ready)


def _cleanup():
    try:
        workspace = _ui.workspaces.itemById('FusionSolidEnvironment')
        panel = workspace.toolbarPanels.itemById('SolidScriptsAddinsPanel')
        control = panel.controls.itemById(CMD_ID_SHOW_GRAPH)
        if control:
            control.deleteMe()
    except Exception:
        pass

    try:
        cmd_def = _ui.commandDefinitions.itemById(CMD_ID_SHOW_GRAPH)
        if cmd_def:
            cmd_def.deleteMe()
    except Exception:
        pass

    try:
        palette = get_palette()
        if palette:
            palette.deleteMe()
    except Exception:
        pass

    try:
        _app.unregisterCustomEvent(DESCRIPTION_READY_EVENT_ID)
    except Exception:
        pass

    _handlers.clear()


def run(context):
    global _app, _ui
    try:
        _app = adsk.core.Application.get()
        _ui = _app.userInterface
        _initialize()
    except Exception:
        if _ui:
            _ui.messageBox(
                'CADtributions failed to start:\n{}'.format(traceback.format_exc())
            )


def stop(context):
    try:
        _cleanup()
    except Exception:
        if _ui:
            _ui.messageBox(
                'CADtributions failed to stop:\n{}'.format(traceback.format_exc())
            )
