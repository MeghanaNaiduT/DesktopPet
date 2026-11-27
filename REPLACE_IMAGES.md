# Changing or adding companions

## Pictures per companion (folder `tools\pets\<id>\`)
| File | What it shows | Required |
|---|---|---|
| `open.png`   | front view, sitting/standing, eyes open, calm smile | **yes** |
| `closed.png` | exactly the same picture with eyes gently closed (blink) | optional |
| `happy.png`  | exactly the same picture with happy closed eyes and an open smile | optional |

* PNG, about 1024 px, whole animal visible and centred, same size/position/pose in all three.
* Background: transparent PNG, or one flat colour that is **magenta** or **teal** (shadows and gradients are fine).
  It is removed automatically; the small Gemini sparkle in the bottom-right corner is painted out automatically.
* Missing `closed`/`happy` pictures fall back to `open` (no blink / no happy face), except for companions listed with
  eye positions in `tools\build_sprites.py` (Remi), whose closed and happy eyes are drawn for you.

## Replace an existing companion
1. Overwrite the pictures in `tools\pets\<id>\` (ids: mochi, remi, finn, pogo, boba).
2. Double-click **Rebuild Sprites.bat** (internet once, to install helper libraries; the app stays offline).
3. Quit Desktop Pet from the tray icon and start it again.

## Add a new companion
1. Create `tools\pets\<newid>\` with the pictures above.
2. Add `"<newid>": {}` to `PETS` in `tools\build_sprites.py` and `"<newid>": {"name": "...", "kind": "..."}` to `PETS` in
   `desktop_pet\core.py`.
3. Run **Rebuild Sprites.bat**, restart. The companion appears in the Add/Edit dialog.
