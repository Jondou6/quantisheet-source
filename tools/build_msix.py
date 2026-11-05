"""Build a Microsoft Store MSIX package from the PUBLIC build (key always
required, no contact list) - the Store route (Jon, Oct 28). Nothing is
signed or submitted here: the Store signs the package after
certification. The package identity (Name / Publisher) comes from
Partner Center once the app name is reserved; until then
installer/msix_identity.json holds placeholders and the package is only
good for checking that it builds and validates.

    python tools/build_msix.py            -> release\\msix\\QuantiSheet-<v>.msix

Steps: copy dist\\QuantiSheet-public to a layout folder, write
AppxManifest.xml and the logo images, then MakeAppx pack (which checks
the manifest against the schema)."""
import glob
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app import __version__ as V  # noqa: E402

BUILD = os.path.join(os.environ.get("LOCALAPPDATA", ""), "QuantiSheetBuild")
SRC = os.path.join(BUILD, "dist", "QuantiSheet-public")
LAYOUT = os.path.join(BUILD, "msix", "layout")
OUT_DIR = os.path.join(ROOT, "release", "msix")
IDENTITY = os.path.join(ROOT, "installer", "msix_identity.json")
DEFAULT_ID = {"Name": "PLACEHOLDER.QuantiSheet",
              "Publisher": "CN=PLACEHOLDER-FROM-PARTNER-CENTER",
              "PublisherDisplayName": "QuantiSheet",
              "_note": "Replace Name / Publisher / PublisherDisplayName with "
                       "the values Partner Center shows under Product "
                       "identity once the app name is reserved."}


def store_version(v):
    """The Store's package version: four parts, the first not 0 and the
    last 0 (Microsoft's app package requirements). QuantiSheet 1.0.0 is
    Store 1.0.0.0 - the same number everywhere (Jon, Oct 30)."""
    parts = [int(p) for p in v.split(".")[:3]]
    while len(parts) < 3:
        parts.append(0)
    if parts[0] < 1:
        raise ValueError(f"version {v}: the Store won't take a version "
                         "starting with 0")
    return ".".join(str(p) for p in parts) + ".0"


STORE_SPLASH = os.path.join(ROOT, "splash_store.png")


def store_splash(layout):
    """The Store copy's start screen: QuantiSheet only, without the
    company's logo and "by ..." line (Jon, Oct 30). Replaces every
    splash.png in the package."""
    if not os.path.isfile(STORE_SPLASH):
        raise SystemExit("splash_store.png is missing - the Store copy "
                         "must not carry the company splash")
    found = glob.glob(os.path.join(layout, "**", "splash.png"),
                      recursive=True)
    if not found:
        raise SystemExit("no splash.png in the package to replace")
    for f in found:
        shutil.copyfile(STORE_SPLASH, f)
    return found


def mark_store(layout, package_name):
    """build.json in the package's app\\data says "store" and names the
    package, so that copy needs no license key (app/betalicense.py)."""
    found = glob.glob(os.path.join(layout, "**", "app", "data",
                                   "build.json"), recursive=True)
    if len(found) != 1:
        raise SystemExit("the public build has no single app\\data\\"
                         "build.json - can't mark the Store copy")
    with open(found[0], encoding="utf-8") as f:
        if json.load(f).get("edition") != "public":
            raise SystemExit("not the public build - the Store copy is "
                             "made from the public one only")
    with open(found[0], "w", encoding="utf-8") as f:
        json.dump({"edition": "store", "package": package_name}, f)
    return found[0]


MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<Package
  xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
  xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
  xmlns:uap10="http://schemas.microsoft.com/appx/manifest/uap/windows10/10"
  xmlns:uap2="http://schemas.microsoft.com/appx/manifest/uap/windows10/2"
  xmlns:uap3="http://schemas.microsoft.com/appx/manifest/uap/windows10/3"
  xmlns:desktop="http://schemas.microsoft.com/appx/manifest/desktop/windows10"
  xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
  IgnorableNamespaces="uap uap2 uap3 uap10 desktop rescap">
  <Identity Name="{Name}" Publisher="{Publisher}" Version="{version}"
            ProcessorArchitecture="x64" />
  <Properties>
    <DisplayName>QuantiSheet</DisplayName>
    <PublisherDisplayName>{PublisherDisplayName}</PublisherDisplayName>
    <Logo>Assets\\StoreLogo.png</Logo>
  </Properties>
  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.17763.0"
                        MaxVersionTested="10.0.26100.0" />
  </Dependencies>
  <Resources>
    <Resource Language="en-us" />
  </Resources>
  <Applications>
    <Application Id="QuantiSheet" Executable="QuantiSheet.exe"
                 EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements DisplayName="QuantiSheet"
          Description="PDF takeoff, estimating and project tools for construction"
          BackgroundColor="transparent"
          Square150x150Logo="Assets\\Square150x150Logo.png"
          Square44x44Logo="Assets\\Square44x44Logo.png">
        <uap:DefaultTile Wide310x150Logo="Assets\\Wide310x150Logo.png" />
      </uap:VisualElements>
      <Extensions>
        <uap:Extension Category="windows.fileTypeAssociation">
          <uap:FileTypeAssociation Name="pdf">
            <uap:DisplayName>PDF Document (QuantiSheet)</uap:DisplayName>
            <uap:SupportedFileTypes>
              <uap:FileType ContentType="application/pdf">.pdf</uap:FileType>
            </uap:SupportedFileTypes>
            <!-- the right-click actions the setup copy adds (Nov 4,
                 review QS-008): app/shellverbs.py -->
            <uap2:SupportedVerbs>
              <uap3:Verb Id="QuantiSheetOpen" Parameters="&quot;%1&quot;">Open in QuantiSheet</uap3:Verb>
              <uap3:Verb Id="QuantiSheetReduce" Parameters="--qs-reduce &quot;%1&quot;">Reduce size (QuantiSheet)</uap3:Verb>
            </uap2:SupportedVerbs>
          </uap:FileTypeAssociation>
        </uap:Extension>
        <uap:Extension Category="windows.fileTypeAssociation">
          <uap:FileTypeAssociation Name="qstools">
            <uap:DisplayName>QuantiSheet Tool Set</uap:DisplayName>
            <uap:SupportedFileTypes>
              <uap:FileType>.qstools</uap:FileType>
            </uap:SupportedFileTypes>
          </uap:FileTypeAssociation>
        </uap:Extension>
      </Extensions>
    </Application>
  </Applications>
  <Capabilities>
    <rescap:Capability Name="runFullTrust" />
  </Capabilities>
</Package>
"""

LOGOS = {"Square44x44Logo.png": (44, 44), "Square150x150Logo.png": (150, 150),
         "StoreLogo.png": (50, 50), "Wide310x150Logo.png": (310, 150)}


def _makeappx():
    hit = shutil.which("makeappx.exe")
    if hit:
        return hit
    found = sorted(glob.glob(r"C:\Program Files (x86)\Windows Kits\10\bin"
                             r"\*\x64\makeappx.exe"))
    return found[-1] if found else None


def _logos(dest):
    from PIL import Image
    src = Image.open(os.path.join(ROOT, "icon.png")).convert("RGBA")
    os.makedirs(dest, exist_ok=True)
    for name, (w, h) in LOGOS.items():
        side = min(w, h)
        im = src.copy()
        im.thumbnail((side, side), Image.LANCZOS)
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        canvas.paste(im, ((w - im.width) // 2, (h - im.height) // 2), im)
        canvas.save(os.path.join(dest, name))


def main():
    if not os.path.isdir(SRC):
        raise SystemExit(f"no public build at {SRC} - run "
                         "tools/build_installer.py first")
    if not os.path.isfile(IDENTITY):
        with open(IDENTITY, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_ID, f, indent=1)
    with open(IDENTITY, encoding="utf-8") as f:
        ident = json.load(f)
    placeholder = "PLACEHOLDER" in ident["Name"] + ident["Publisher"]
    if os.path.isdir(LAYOUT):
        shutil.rmtree(LAYOUT)
    print("copying", SRC)
    shutil.copytree(SRC, LAYOUT)
    _logos(os.path.join(LAYOUT, "Assets"))
    mark_store(LAYOUT, ident["Name"])
    store_splash(LAYOUT)
    with open(os.path.join(LAYOUT, "AppxManifest.xml"), "w",
              encoding="utf-8") as f:
        f.write(MANIFEST.format(version=store_version(V), **ident))
    tool = _makeappx()
    if not tool:
        raise SystemExit("MakeAppx isn't on this PC (Windows SDK) - the "
                         "layout is ready at " + LAYOUT)
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"QuantiSheet-{V}.msix")
    r = subprocess.run([tool, "pack", "/d", LAYOUT, "/p", out, "/o"],
                       capture_output=True, text=True)
    print(r.stdout[-3000:])
    print(r.stderr[-2000:])
    print("exit", r.returncode)
    if r.returncode == 0:
        print("package:", out, f"({os.path.getsize(out) / 1e6:.0f} MB)")
        if placeholder:
            print("NOTE: placeholder identity - not for submission until the "
                  "Partner Center values are in installer/msix_identity.json")
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
