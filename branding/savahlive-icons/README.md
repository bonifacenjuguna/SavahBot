# SavahLive icons

One 24x24 SVG per icon, drawn with `currentColor` so it takes whatever colour you give it.
The Android app uses the same shapes as vector drawables (`android/app/src/main/res/drawable/ic_<name>.xml`) and tints them
with the panel theme, so changing the theme recolours every icon. To change an icon, edit its SVG path and regenerate the XML
(the path data is identical in both files).
