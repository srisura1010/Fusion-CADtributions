# Fusion-CADtributions

A Fusion 360 add-in that turns your save history into a GitHub style contribution graph. Every time you save a new version of a design, or create a brand new file, it counts as one CADtribution (like a contribution).

Think of it like a commit graph, but for CAD work.

Currently getting published in the Fusion App Store for download. Feel free to raise an issue on this repository for feature requests/bug reporting/questions.

## Features

- Tracks every save automatically, no manual logging
- Tells new files apart from new versions of existing files
- GitHub style heatmap with color levels based on your own activity (uses quartiles, same approach GitHub uses, so the scale is relative to you, not a fixed scale)
- Rolling "last 365 days" view, plus a year picker for any specific calendar year
- Pulls the description straight from Fusion's own save dialog, so you don't have to type anything extra
- Click any entry to jump straight to that file in Fusion
- Current streak, longest streak, and total counts
- Filter by project
- Export the graph as a PNG
- Everything stored locally in a simple JSON file, no accounts, no external servers

## Screenshots

<img width="1038" height="825" alt="image" src="https://github.com/user-attachments/assets/4df1c97e-8a7a-4249-a045-c4dd86c2374c" />
<img width="1011" height="233" alt="image" src="https://github.com/user-attachments/assets/5aa2baaf-241b-4de9-9380-b97cebd41338" />
<img width="1042" height="825" alt="image" src="https://github.com/user-attachments/assets/697b32ec-6309-4bea-9c91-191f9c805200" />
<img width="1116" height="182" alt="Link-highlighted_view_img" src="https://github.com/user-attachments/assets/ee579c6c-be42-4c4a-a81f-d666d953e58c" />



## Installation

1. Download or clone this repo.
2. Open Fusion 360 and go to **Utilities > Add-Ins > Scripts and Add-Ins** (or press `Shift+S`).
3. On the **Add-Ins** tab, click the option to add a script or add-in from your device, then select the `CADtributions` folder.
4. Select it in the list and toggle it on. Check **Run on Startup** if you want it to load automatically every time.
5. Save any design. That's your first CADtribution.
6. Click the CADtributions button in the ADD-INS panel (SOLID tab) to open the graph.

## How it works

The add-in listens for Fusion's save event. When a file is saved to a Fusion Data Panel project, it reads the real version number Fusion assigns, so every save is counted exactly once and new files are correctly identified as new. That data gets written to a small JSON file alongside the add-in, and a panel built with plain HTML, CSS, and JavaScript renders it as a graph.

No external libraries, no network calls, everything runs locally.

## Known limitations

- Data is stored locally on the machine you're using. It does not sync across multiple computers.
- If you rename or move a file after saving it, older entries will still show the old name and location. Clicking still opens the correct file though, since that's based on a stable file ID, not the displayed name.
- The JSON file grows with every save. Fine for personal use at normal scale, not built for massive datasets.

## License

MIT. See [LICENSE](LICENSE) for details.

## Author

Srivatsav Sura, Midvale Utah
