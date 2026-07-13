# Trading Trainer demo video

- `trading-trainer-demo.mp4` — 44.9-second, silent, captioned 1080p H.264 cut
- `cover.png` — 16:9 README preview linked to the video
- `contact-sheet.png` — quick visual overview of the finished edit
- `stills/` — original 1920×1080 browser captures
- `render_video.py` — recreates the title cards, lower thirds, motion, fades, and MP4

The journal and curriculum scenes were captured against a disposable copy of the local database with staged demo progress and trades. The live user database was not modified, and the disposable copy was removed after capture.

To rerender:

```powershell
python -m pip install Pillow imageio-ffmpeg
python .\artifacts\trading-trainer-demo\render_video.py
```
