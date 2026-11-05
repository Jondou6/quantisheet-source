// tools/thumbs.py test: draw a PDF's thumbnail the way Explorer would get it.
class ThumbTest
{
    static int Main(string[] a)
    {
        try
        {
            QuantiSheet.Thumbs.PdfThumbnail.RenderFile(a[0], uint.Parse(a[1]), a[2]);
            System.Console.WriteLine("ok " + a[2]);
            return 0;
        }
        catch (System.Exception e)
        {
            System.Console.WriteLine("FAILED " + e);
            return 1;
        }
    }
}
