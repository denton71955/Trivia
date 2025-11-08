import openpyxl

openpyxl_version = openpyxl.__version__
from PyQt6.QtCore import QT_VERSION_STR, PYQT_VERSION_STR


{
  "graphics": {
    "resolution": {
      "width": 1920,
      "height": 1080
    },
    "fullscreen": True,
    "vSync": True,
    "quality": "high"
  },
  "audio": {
    "masterVolume": 0.8,
    "musicVolume": 0.6,
    "sfxVolume": 0.9
  },
  "controls": {
    "keyBindings": {
      "jump": "Spacebar",
      "attack": "LeftMouse",
      "interact": "E",
      "crouch": "LeftControl"
    },
    "mouseSensitivity": 0.75
  }
}
