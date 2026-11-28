"""Write installer/policy/QuantiSheet.admx and en-US/QuantiSheet.adml from
app/policy.py's SETTINGS (run after adding a setting; tests/test_it_policy
checks they agree)."""
import importlib.util
import os
from xml.sax.saxutils import escape as e

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "policy", os.path.join(ROOT, "app", "policy.py"))
pol = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pol)
S = pol.SETTINGS
GROUPS = [("Licensing", "Licensing and sign-in",
           ["LicenseKey", "AcceptAgreement", "SkipEmailSignIn"]),
          ("Shared", "Shared data and servers",
           ["PriceDatabasePath", "RelayURL", "RelayToken", "AIHost",
            "LogDirectory"]),
          ("Internet", "Internet and AI features",
           ["OfflineMode", "DisableAerial", "DisableWeather",
            "DisableRateLookup", "DisableDocuSign", "DisableDropbox",
            "DisablePackageStatus", "DisableErrorReports", "DropboxAppKey",
            "DisableQuantiLink",
            "QuantiLinkURL", "QuantiLinkKey", "DisableAI",
            "DisableUpdateCheck"])]
EXPLAIN = {
    "DisableUpdateCheck": "Turns off the once-a-day update check. The team "
    "copy downloads one small signed file from the team update host (see "
    "IT_DEPLOYMENT.md), sends no user data, and installs an update only when "
    "the user clicks Update now. The Microsoft Store copy asks the Microsoft "
    "Store on this PC whether an update is waiting and shows a reminder; the "
    "Store does the download and install. Help > Check for Updates Now still "
    "works when the user picks it.",
    "DisableDropbox": "Turns off File > Open from Dropbox and Save to "
    "Dropbox. These contact www.dropbox.com, api.dropboxapi.com and "
    "content.dropboxapi.com, only when a user runs them.",
    "DropboxAppKey": "The App key of the company's Dropbox app "
    "(dropbox.com/developers/apps, Scoped access, Full Dropbox, permissions "
    "files.metadata.read, files.content.read and files.content.write, "
    "redirect URI http://127.0.0.1:53917/). Users then only sign in. The App "
    "secret is not needed and must not be entered anywhere.",
    "LicenseKey": "Enter the beta license key issued to your company. Every "
    "user of the computer is licensed with it and isn't asked for a key. A "
    "valid key a user entered themselves still wins.",
    "AcceptAgreement": "No longer used: QuantiSheet 1.0.0 and later have no "
    "agreement page. Kept so an existing setting does no harm.",
    "SkipEmailSignIn": "Enable on company-managed computers so users aren't "
    "asked for their work email the first time they start QuantiSheet.",
    "PriceDatabasePath": "Location of the shared price database, normally a "
    "UNC path such as \\\\server\\share\\QuantiSheet\\prices.db. Users can't "
    "move or disconnect it while this is set. Every user needs read and "
    "write access to the folder.",
    "RelayURL": "Address of the company's QuantiSheet collaboration relay, "
    "for example ws://quantisheet-relay:8765. Install the relay with "
    "QuantiSheet Server Setup (task: collaboration relay).",
    "RelayToken": "The relay's access token. On the relay server it is in "
    "C:\\ProgramData\\QuantiSheet\\relay\\relay-token.txt (made when Server Setup "
    "installs the relay). Users can read this value, which they need to "
    "connect.",
    "AIHost": "Address of the Ollama server the local AI features use. "
    "Default: http://localhost:11434 (each PC runs its own). Use a shared "
    "server, for example http://ai-server:11434, to avoid installing the "
    "model on every PC.",
    "LogDirectory": "Write log files here instead of each user's profile. "
    "Environment variables are allowed. Each user gets a sub-folder named "
    "after their Windows user name, so Remote Desktop users don't share a "
    "file.",
    "OfflineMode": "Enable to stop QuantiSheet from using the internet at "
    "all: aerial photos, address lookup, site layers, weather, labor-rate "
    "downloads, DocuSign and Dropbox are turned off. Drawings, takeoff and "
    "estimating work as normal.",
    "DisableAerial": "Turns off aerial photos, address lookup and site "
    "layers (flood, wetlands, contours). These contact USGS, the US Census "
    "geocoder, FEMA and USFWS.",
    "DisableWeather": "Turns off weather for daily logs (Open-Meteo).",
    "DisableRateLookup": "Turns off labor-rate downloads from the US Bureau "
    "of Labor Statistics.",
    "DisableDocuSign": "Turns off DocuSign signature requests. QuantiSheet's "
    "own signing still works.",
    "DisablePackageStatus": "Turns off Package Tracker > Check Status, "
    "which sends only a tracking number to the carrier it belongs to (UPS, "
    "FedEx, USPS or DHL) when the user clicks it and has that carrier's "
    "keys. Track (opening the carrier's page) still works. OfflineMode "
    "turns this off too.",
    "DisableErrorReports": "Team copy only: removes Help > Send Error "
    "Reports Automatically, which a tester can turn on to send a short "
    "report (what happened, the QuantiSheet and Windows versions, where in "
    "the program the error was) to reports.quantisheet.com after an error. "
    "It is off unless the tester turns it on; no drawings, job files, file "
    "names, prices or logs are sent. OfflineMode turns this off too.",
    "DisableQuantiLink": "Turns off Home > Send with QuantiLink, which "
    "uploads Project Center files (RFIs, submittals, daily logs, meeting "
    "minutes) to the office's own QuantiLink server and makes share links, "
    "only when a user clicks Send. OfflineMode turns this off too.",
    "QuantiLinkURL": "The address of the office's QuantiLink server, for "
    "example https://files.example.com (https is required). Set it together "
    "with QuantiLinkKey and users can't change the connection.",
    "QuantiLinkKey": "The shared access key (qlt_...) made in QuantiLink "
    "under Account settings > Desktop sync. It is sent only to the "
    "QuantiLink server, never in a web address, and is left out of support "
    "bundles.",
    "DisableAI": "Turns off the local AI features (AI Takeoff, AI review, "
    "brief reading, RFI finder).",
}


def build():
    """The two files' text, (admx, adml), from app/policy.py - the one
    source (tests/test_it_policy checks the shipped files equal it)."""
    names = sum((g[2] for g in GROUPS), [])
    assert sorted(names) == sorted(S), set(S) ^ set(names)
    assert set(EXPLAIN) == set(S), set(S) ^ set(EXPLAIN)
    key = "Software\\Policies\\QuantiSheet"
    admx = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<!-- QuantiSheet Group Policy template. Copy QuantiSheet.admx to',
        '     C:\\Windows\\PolicyDefinitions (or the Central Store) and',
        '     en-US\\QuantiSheet.adml to its en-US sub-folder. -->',
        '<policyDefinitions xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'revision="1.0" schemaVersion="1.0" xmlns="http://schemas.microsoft'
        '.com/GroupPolicy/2006/07/PolicyDefinitions">',
        '  <policyNamespaces>',
        '    <target prefix="quantisheet" '
        'namespace="QuantiSheet.Policies.QuantiSheet" />',
        '    <using prefix="windows" namespace="Microsoft.Policies.Windows" '
        '/>',
        '  </policyNamespaces>',
        '  <resources minRequiredRevision="1.0" />',
        '  <supportedOn>', '    <definitions>',
        '      <definition name="SUPPORTED_QuantiSheet" '
        'displayName="$(string.SUPPORTED_QuantiSheet)" />',
        '    </definitions>', '  </supportedOn>', '  <categories>',
        '    <category name="QuantiSheet" displayName="$(string.QuantiSheet)" />']
    for gid, _n, _ in GROUPS:
        admx.append(f'    <category name="{gid}" displayName="$(string.'
                    f'Cat_{gid})"><parentCategory ref="QuantiSheet" />'
                    '</category>')
    admx += ['  </categories>', '  <policies>']
    for gid, _n, group in GROUPS:
        for k in group:
            head = (f'    <policy name="{k}" class="Both" displayName="$('
                    f'string.{k})" explainText="$(string.{k}_Help)" ')
            if S[k][0] is bool:
                admx += [head + f'key="{key}" valueName="{k}">',
                         f'      <parentCategory ref="{gid}" />',
                         '      <supportedOn ref="SUPPORTED_QuantiSheet" />',
                         '      <enabledValue><decimal value="1" />'
                         '</enabledValue>',
                         '      <disabledValue><decimal value="0" />'
                         '</disabledValue>', '    </policy>']
            else:
                admx += [head + f'presentation="$(presentation.{k})" '
                         f'key="{key}">',
                         f'      <parentCategory ref="{gid}" />',
                         '      <supportedOn ref="SUPPORTED_QuantiSheet" />',
                         '      <elements>',
                         f'        <text id="{k}" valueName="{k}" '
                         'required="true" />',
                         '      </elements>', '    </policy>']
    admx += ['  </policies>', '</policyDefinitions>', '']
    adml = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<policyDefinitionResources xmlns:xsd="http://www.w3.org/2001/'
        'XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'revision="1.0" schemaVersion="1.0" xmlns="http://schemas.microsoft'
        '.com/GroupPolicy/2006/07/PolicyDefinitions">',
        '  <displayName>QuantiSheet</displayName>',
        '  <description>QuantiSheet settings managed by the IT department.'
        '</description>',
        '  <resources>', '    <stringTable>',
        '      <string id="QuantiSheet">QuantiSheet</string>',
        '      <string id="SUPPORTED_QuantiSheet">QuantiSheet 1.0.0 and '
        'later</string>']
    for gid, name, _ in GROUPS:
        adml.append(f'      <string id="Cat_{gid}">{e(name)}</string>')
    for k in S:
        adml.append(f'      <string id="{k}">{e(S[k][1])}</string>')
        adml.append(f'      <string id="{k}_Help">{e(EXPLAIN[k])}</string>')
    adml += ['    </stringTable>', '    <presentationTable>']
    for k in S:
        if S[k][0] is not bool:
            adml += [f'      <presentation id="{k}">',
                     f'        <textBox refId="{k}"><label>{e(k)}:</label>'
                     '</textBox>', '      </presentation>']
    adml += ['    </presentationTable>', '  </resources>',
             '</policyDefinitionResources>', '']
    return "\n".join(admx), "\n".join(adml)


def paths():
    d = os.path.join(ROOT, "installer", "policy")
    return (os.path.join(d, "QuantiSheet.admx"),
            os.path.join(d, "en-US", "QuantiSheet.adml"))


def main():
    for path, text in zip(paths(), build()):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    print("written", len(S), "settings")


if __name__ == "__main__":
    main()
