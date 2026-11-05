// QuantiSheet PDF thumbnails for File Explorer (Nov 4, experimental, off by
// default). A thumbnail handler: Windows hands it the PDF as a stream and
// asks for a picture of the first page. It draws the page with Windows' own
// PDF renderer (Windows.Data.Pdf). Windows runs thumbnail handlers in a
// separate, isolated process, so a bad file can't take Explorer down.
// Turned on and off per user by tools/thumbs.py (HKCU only).
using System;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Threading;
using System.Threading.Tasks;
using Windows.Data.Pdf;
using Windows.Foundation;
using Windows.Storage.Streams;

namespace QuantiSheet.Thumbs
{
    [ComImport, Guid("b824b49d-22ac-4161-ac8a-9916e8fa3f7f"),
     InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IInitializeWithStream
    {
        void Initialize(IStream pstream, uint grfMode);
    }

    [ComImport, Guid("e357fccd-a995-4576-b01f-234630154e96"),
     InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IThumbnailProvider
    {
        void GetThumbnail(uint cx, out IntPtr phbmp, out uint pdwAlpha);
    }

    [ComVisible(true), Guid("6E1B2C3A-9D47-4F0B-8A51-2C7D0E4B9F16"),
     ClassInterface(ClassInterfaceType.None)]
    public class PdfThumbnail : IInitializeWithStream, IThumbnailProvider
    {
        const int MaxBytes = 300 * 1024 * 1024;     // bigger files: no thumb
        byte[] data;

        public void Initialize(IStream pstream, uint grfMode)
        {
            var ms = new MemoryStream();
            var buf = new byte[1 << 16];
            IntPtr read = Marshal.AllocCoTaskMem(4);
            try
            {
                while (true)
                {
                    pstream.Read(buf, buf.Length, read);
                    int n = Marshal.ReadInt32(read);
                    if (n <= 0) break;
                    ms.Write(buf, 0, n);
                    if (ms.Length > MaxBytes)
                        throw new COMException("too big", unchecked((int)0x80004005));
                }
            }
            finally
            {
                Marshal.FreeCoTaskMem(read);
                Marshal.ReleaseComObject(pstream);
            }
            data = ms.ToArray();
        }

        public void GetThumbnail(uint cx, out IntPtr phbmp, out uint pdwAlpha)
        {
            phbmp = IntPtr.Zero;
            pdwAlpha = 0;          // WTSAT_UNKNOWN
            if (data == null) throw new COMException("no data", unchecked((int)0x80004005));
            var t = Task.Run(() => Render(data, cx));
            if (!t.Wait(15000))
                throw new COMException("timeout", unchecked((int)0x80004005));
            using (var bmp = t.Result)
            {
                phbmp = bmp.GetHbitmap(Color.White);
            }
        }

        // for tools/thumbs.py test: the same drawing, from a file
        public static void RenderFile(string path, uint cx, string outPng)
        {
            using (var bmp = Render(File.ReadAllBytes(path), cx))
                bmp.Save(outPng, System.Drawing.Imaging.ImageFormat.Png);
        }

        // waiting on Windows' async calls without the .NET helpers (they
        // need the full Windows SDK metadata, which this PC needn't have)
        static T Wait<T>(IAsyncOperation<T> op)
        {
            var until = DateTime.UtcNow.AddSeconds(15);
            while (op.Status == AsyncStatus.Started)
            {
                if (DateTime.UtcNow > until) { op.Cancel(); throw new TimeoutException(); }
                Thread.Sleep(5);
            }
            if (op.Status != AsyncStatus.Completed)
                throw op.ErrorCode ?? new InvalidOperationException("failed");
            return op.GetResults();
        }

        static void Wait(IAsyncAction op)
        {
            var until = DateTime.UtcNow.AddSeconds(15);
            while (op.Status == AsyncStatus.Started)
            {
                if (DateTime.UtcNow > until) { op.Cancel(); throw new TimeoutException(); }
                Thread.Sleep(5);
            }
            if (op.Status != AsyncStatus.Completed)
                throw op.ErrorCode ?? new InvalidOperationException("failed");
            op.GetResults();
        }

        static Bitmap Render(byte[] bytes, uint cx)
        {
            var ras = new InMemoryRandomAccessStream();
            var w = new DataWriter(ras);
            w.WriteBytes(bytes);
            Wait(w.StoreAsync());
            w.DetachStream();
            ras.Seek(0);
            var doc = Wait(PdfDocument.LoadFromStreamAsync(ras));
            using (var page = doc.GetPage(0))
            {
                var opt = new PdfPageRenderOptions();
                double pw = page.Size.Width, ph = page.Size.Height;
                double f = cx / Math.Max(pw, ph);
                opt.DestinationWidth = (uint)Math.Max(1, Math.Round(pw * f));
                opt.DestinationHeight = (uint)Math.Max(1, Math.Round(ph * f));
                opt.BackgroundColor = Windows.UI.Color.FromArgb(255, 255, 255, 255);
                var outs = new InMemoryRandomAccessStream();
                Wait(page.RenderToStreamAsync(outs, opt));
                outs.Seek(0);
                var png = new byte[outs.Size];
                var r = new DataReader(outs);
                Wait(r.LoadAsync((uint)outs.Size));
                r.ReadBytes(png);
                using (var m = new MemoryStream(png))
                using (var img = Image.FromStream(m))
                {
                    return new Bitmap(img);
                }
            }
        }
    }
}
