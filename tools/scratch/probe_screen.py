"""Print the screens' scaling as Qt sees them (for sharp rendering)."""
import sys
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv[:1])
for s in app.screens():
    g = s.geometry()
    print(s.name(), f"{g.width()}x{g.height()} logical,",
          f"scale {s.devicePixelRatio():g},",
          f"dpi {s.logicalDotsPerInch():.0f}/{s.physicalDotsPerInch():.0f}")
