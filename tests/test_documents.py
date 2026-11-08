import tempfile
import unittest
from pathlib import Path
from documents import extract, import_document


def text_pdf():
    stream = b'BT /F1 12 Tf 50 750 Td (Hello local PDF) Tj ET'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
    result = b'%PDF-1.4\n'
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result += str(i).encode()+b' 0 obj\n'+obj+b'\nendobj\n'
    start = len(result)
    result += b'xref\n0 6\n0000000000 65535 f \n'
    result += b''.join(f'{offset:010} 00000 n \n'.encode() for offset in offsets[1:])
    result += b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n'+str(start).encode()+b'\n%%EOF'
    return result

class DocumentTests(unittest.TestCase):
    def test_pdf_text_extraction(self):
        pages = extract('book.pdf', text_pdf())
        self.assertEqual(pages[0][0], 'Страница 1')
        self.assertIn('Hello local PDF', pages[0][1])

    def test_plaintext_escaping_and_stable_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            content = 'Привет <script>alert(1)</script>'.encode()
            first = import_document(tmp, '../../book.txt', content)
            second = import_document(tmp, 'book.txt', content)
            self.assertEqual(first, second)
            html = (Path(tmp)/(first+'.html')).read_text()
            self.assertIn('&lt;script&gt;', html)
            self.assertNotIn('<script>', html)
            self.assertEqual((Path(tmp)/(first+'.source')).read_bytes(), content)

    def test_html_scripts_not_read(self):
        pages = extract('book.html', b'<p>Read me</p><script>do not read</script>')
        self.assertIn('Read me', pages[0][1])
        self.assertNotIn('do not read', pages[0][1])

    def test_image_only_and_password_pdf(self):
        from pypdf import PdfWriter
        import io
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        blank = io.BytesIO()
        writer.write(blank)
        with self.assertRaisesRegex(ValueError, 'OCR'):
            extract('scan.pdf', blank.getvalue())
        writer.encrypt('secret')
        encrypted = io.BytesIO()
        writer.write(encrypted)
        with self.assertRaisesRegex(ValueError, 'паролем'):
            extract('private.pdf', encrypted.getvalue())

    def test_empty_and_unsupported(self):
        for name, content in [('book.txt', b''), ('file.exe', b'binary'), ('bad.pdf', b'broken')]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                extract(name, content)
