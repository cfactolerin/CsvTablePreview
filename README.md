# CSV Table Preview

An in-editor, read-only CSV/TSV table preview created for Sublime Text 3.2.
The source opens on the left and the rendered preview opens in a group to its
right. Source fields and preview cells share a column palette. No browser,
network service, third-party package, or external Python installation is needed.

This is a prototype, not yet available through Package Control.

## Compatibility

- **Sublime Text 3.2 (build 3211), macOS:** developed and tested on this version.
- **Sublime Text 4:** not tested; compatibility is not confirmed.
- **Windows and Linux:** keybindings are included, but the interface has not been
  tested on these platforms.

## Installation

Install manually while the package is not available through Package Control:

1. Download or clone this repository.
2. In Sublime Text, choose **Preferences → Browse Packages…** to open the active
   `Packages` directory. On macOS, Preferences is under the Sublime Text menu.
3. Copy the repository into that directory as a folder named
   **`CsvTablePreview`**. The file layout should be
   `Packages/CsvTablePreview/plugin.py`, not an extra nested repository folder.
4. Restart Sublime Text.
5. Open a CSV or TSV file and run **CSV: Open Table Preview** from the command
   palette (`Cmd+Shift+P` on macOS, `Ctrl+Shift+P` on Windows/Linux).

No dependencies need to be installed. Do not install the package twice, for
example as both a copied folder and a development symlink.

### Development installation

On macOS or Linux, you can link your checkout into the `Packages` directory
instead of copying it. Replace both example paths with your actual paths:

```sh
ln -s "/path/to/CsvTablePreview" "/path/to/Packages/CsvTablePreview"
```

The destination must not already exist. This lets Sublime load changes from
your checkout directly.

### Uninstall

Close any open table previews, then quit Sublime Text and remove the
`Packages/CsvTablePreview` folder or symlink. If you used a symlink, remove only
the link, not your checkout. You can also remove the optional
`Packages/User/CsvTablePreview.sublime-settings` file and the generated
`Packages/User/CsvTablePreview-*.sublime-color-scheme` and
`Packages/User/CsvTablePreview-*.sublime-syntax` files.

## Usage

Open a saved `.csv`, `.tsv`, or `.tab` file. Run **CSV: Open Table Preview** from
the command palette. Use **CSV: Toggle Table Preview** or `Cmd+Option+T` on macOS
(`Ctrl+Alt+T` on Linux/Windows) to close or reopen it.

Edit the source; the preview updates after a short pause. Clicking a preview
cell selects its original source field, including quotes. Values remain text,
including long IDs and leading zeros. The preview never rewrites the CSV.

Columns are paged to fit the pane. Use **Next** and **Previous** above the table
to see more columns. Quoted multiline cells display `↵`; long cells display `…`.
Select the corresponding source field to read its full value.

## Settings

Automatic preview is off by default. To open the preview automatically for CSV
and TSV files, set `auto_preview` to `true`.

Override settings in `Packages/User/CsvTablePreview.sublime-settings`:

```json
{
    "auto_preview": true,
    "max_rows": 500,
    "max_columns": 100,
    "max_cell_width": 32,
    "max_source_chars": 2000000,
    "first_row_is_header": true,
    "delimiter": null
}
```

With `delimiter: null`, tabs are used for `.tsv`/`.tab`; other files are sniffed
for comma, semicolon, tab, or pipe delimiters. Set `delimiter` explicitly for
ambiguous files. The first row is styled as a header by default.

The preview limits do not truncate the source. Files over the character limit
show an explanation instead of rendering a partial file. Malformed CSV shows a
parsing error instead of a stale preview.

The package creates small color-scheme snapshots and delimiter-specific syntax
files in `Packages/User` so its source colors also work with older `.tmTheme`
themes. The previous source scheme and syntax are restored when the preview
closes. Other files keep their existing theme.

## Limitations

This is a preview, not an editable spreadsheet or an XLSX viewer. Sublime's
minihtml renderer does not implement HTML tables or input controls. The preview
uses styled, fixed-width inline cells that work in Sublime Text 3.2. Unicode
widths are approximate for emoji and some font combinations.

Sublime Text 4 and other platforms need live UI testing before compatibility
can be claimed. A license, release tag, and Package Control submission are still
needed before publication.

## Tests

Run `python3 -m unittest discover -s tests -v` from the repository root.
