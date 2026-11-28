// QuantiSheet Outlook proof (stage 2 of the Outlook plan). A throw-away
// test page, not the add-in. It answers two questions in the Outlook it
// is opened in:
//   1. Can a web add-in read a PDF attachment's bytes?
//   2. Can it reach a program listening on this computer (127.0.0.1)?
// It talks only to Outlook and to tools/outlook_proof_listener.py on the
// same computer. Nothing goes anywhere else, and nothing is kept.
(function () {
  const PORT = 47321;
  const lines = [];
  const steps = document.getElementById("steps");

  function note(ok, text) {
    const li = document.createElement("li");
    const mark = document.createElement("span");
    mark.className = ok ? "ok" : "no";
    mark.textContent = ok ? "Yes: " : "No: ";
    li.appendChild(mark);
    li.appendChild(document.createTextNode(text));
    steps.appendChild(li);
    lines.push((ok ? "YES " : "NO  ") + text);
    document.getElementById("report").textContent = lines.join("\n");
  }

  function attachmentBytes(att) {
    return new Promise((resolve, reject) => {
      const item = Office.context.mailbox.item;
      if (!item.getAttachmentContentAsync) {
        reject(new Error("this Outlook has no getAttachmentContentAsync"));
        return;
      }
      item.getAttachmentContentAsync(att.id, (res) => {
        if (res.status !== Office.AsyncResultStatus.Succeeded) {
          reject(new Error(res.error && res.error.message));
          return;
        }
        const c = res.value;
        if (c.format !== Office.MailboxEnums.AttachmentContentFormat.Base64) {
          reject(new Error("came as " + c.format + ", not a file"));
          return;
        }
        const bin = atob(c.content);
        const bytes = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
        resolve(bytes);
      });
    });
  }

  async function run() {
    steps.textContent = "";
    lines.length = 0;
    const host = Office.context.diagnostics || {};
    lines.push("Outlook: " + (host.host || "?") + " " +
               (host.version || "?") + " on " + (host.platform || "?"));
    const item = Office.context.mailbox.item;
    const atts = (item && item.attachments) || [];
    const pdfs = atts.filter((a) => /\.pdf$/i.test(a.name || "") &&
                                    !a.isInline);
    note(atts.length > 0, atts.length + " attachment(s) seen on this " +
         "email, " + pdfs.length + " of them PDF");
    let bytes = null;
    if (pdfs.length) {
      try {
        bytes = await attachmentBytes(pdfs[0]);
        const head = String.fromCharCode.apply(null, bytes.subarray(0, 5));
        note(head === "%PDF-", "read the first PDF's bytes (" +
             bytes.length + " bytes, starts " + JSON.stringify(head) + ")");
      } catch (e) {
        note(false, "could not read the PDF's bytes: " + e.message);
      }
    } else {
      note(false, "open an email that has a PDF attached, then run again");
    }
    const base = "http://127.0.0.1:" + PORT;
    try {
      const r = await fetch(base + "/ping", { cache: "no-store" });
      note(r.ok, "reached the test program on this computer (answer " +
           r.status + ")");
    } catch (e) {
      note(false, "could not reach the test program on this computer: " +
           e.message + " (is tools/outlook_proof_listener.py running?)");
    }
    if (bytes) {
      try {
        const r = await fetch(base + "/pdf", {
          method: "POST", body: bytes,
          headers: { "Content-Type": "application/pdf" }
        });
        const said = await r.text();
        note(r.ok, "handed the PDF to the test program: " + said);
      } catch (e) {
        note(false, "could not hand the PDF over: " + e.message);
      }
    }
  }

  Office.onReady(() => {
    document.getElementById("run").addEventListener("click", () => {
      run().catch((e) => note(false, "the test stopped: " + e.message));
    });
  });
})();
