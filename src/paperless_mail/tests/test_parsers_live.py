import hashlib
import os
from unittest import mock
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest
from django.test import TestCase
from documents.parsers import ParseError
from documents.parsers import run_convert
from paperless_mail.parsers import MailDocumentParser
from pdfminer.high_level import extract_text


class TestParserLive(TestCase):
    SAMPLE_FILES = os.path.join(os.path.dirname(__file__), "samples")

    def setUp(self) -> None:
        self.parser = MailDocumentParser(logging_group=None)

    def tearDown(self) -> None:
        self.parser.cleanup()

    @staticmethod
    def hashfile(file):
        buf_size = 65536  # An arbitrary (but fixed) buffer
        sha256 = hashlib.sha256()
        with open(file, "rb") as f:
            while True:
                data = f.read(buf_size)
                if not data:
                    break
                sha256.update(data)
        return sha256.hexdigest()

    # Only run if convert is available
    @pytest.mark.skipif(
        "PAPERLESS_TEST_SKIP_CONVERT" in os.environ,
        reason="PAPERLESS_TEST_SKIP_CONVERT set, skipping Test",
    )
    @mock.patch("paperless_mail.parsers.MailDocumentParser.generate_pdf")
    @mock.patch("documents.loggers.LoggingMixin.log")  # Disable log output
    def test_get_thumbnail(self, m, mock_generate_pdf: mock.MagicMock):
        mock_generate_pdf.return_value = os.path.join(
            self.SAMPLE_FILES,
            "simple_text.eml.pdf",
        )
        thumb = self.parser.get_thumbnail(
            os.path.join(self.SAMPLE_FILES, "simple_text.eml"),
            "message/rfc822",
        )
        self.assertTrue(os.path.isfile(thumb))

        expected = os.path.join(self.SAMPLE_FILES, "simple_text.eml.pdf.webp")

        self.assertEqual(
            self.hashfile(thumb),
            self.hashfile(expected),
            f"Created Thumbnail {thumb} differs from expected file {expected}",
        )

    @mock.patch("documents.loggers.LoggingMixin.log")  # Disable log output
    def test_tika_parse(self, m):
        html = '<html><head><meta http-equiv="content-type" content="text/html; charset=UTF-8"></head><body><p>Some Text</p></body></html>'
        expected_text = "\n\n\n\n\n\n\n\n\nSome Text\n"

        tika_server_original = self.parser.tika_server

        # Check if exception is raised when Tika cannot be reached.
        with pytest.raises(ParseError):
            self.parser.tika_server = ""
            self.parser.tika_parse(html)

        # Check unsuccessful parsing
        self.parser.tika_server = tika_server_original

        parsed = self.parser.tika_parse(None)
        self.assertEqual("", parsed)

        # Check successful parsing
        parsed = self.parser.tika_parse(html)
        self.assertEqual(expected_text, parsed)

    @pytest.mark.skipif(
        "GOTENBERG_LIVE" not in os.environ,
        reason="No gotenberg server",
    )
    @mock.patch("paperless_mail.parsers.MailDocumentParser.generate_pdf_from_mail")
    @mock.patch("paperless_mail.parsers.MailDocumentParser.generate_pdf_from_html")
    def test_generate_pdf_gotenberg_merging(
        self,
        mock_generate_pdf_from_html: mock.MagicMock,
        mock_generate_pdf_from_mail: mock.MagicMock,
    ):

        with open(os.path.join(self.SAMPLE_FILES, "first.pdf"), "rb") as first:
            mock_generate_pdf_from_mail.return_value = first.read()

        with open(os.path.join(self.SAMPLE_FILES, "second.pdf"), "rb") as second:
            mock_generate_pdf_from_html.return_value = second.read()

        pdf_path = self.parser.generate_pdf(os.path.join(self.SAMPLE_FILES, "html.eml"))
        self.assertTrue(os.path.isfile(pdf_path))

        extracted = extract_text(pdf_path)
        expected = (
            "first\tPDF\tto\tbe\tmerged.\n\n\x0csecond\tPDF\tto\tbe\tmerged.\n\n\x0c"
        )
        self.assertEqual(expected, extracted)

    # Only run if convert is available
    @pytest.mark.skipif(
        "PAPERLESS_TEST_SKIP_CONVERT" in os.environ,
        reason="PAPERLESS_TEST_SKIP_CONVERT set, skipping Test",
    )
    @mock.patch("documents.loggers.LoggingMixin.log")  # Disable log output
    def test_generate_pdf_from_mail(self, m):
        # TODO
        mail = self.parser.get_parsed(os.path.join(self.SAMPLE_FILES, "html.eml"))

        pdf_path = os.path.join(self.parser.tempdir, "test_generate_pdf_from_mail.pdf")

        with open(pdf_path, "wb") as file:
            file.write(self.parser.generate_pdf_from_mail(mail))
            file.close()

        converted = os.path.join(parser.tempdir, "test_generate_pdf_from_mail.webp")
        run_convert(
            density=300,
            scale="500x5000>",
            alpha="remove",
            strip=True,
            trim=False,
            auto_orient=True,
            input_file=f"{pdf_path}",  # Do net define an index to convert all pages.
            output_file=converted,
            logging_group=None,
        )
        self.assertTrue(os.path.isfile(converted))
        thumb_hash = self.hashfile(converted)

        # The created pdf is not reproducible. But the converted image should always look the same.
        expected_hash = (
            "8734a3f0a567979343824e468cd737bf29c02086bbfd8773e94feb986968ad32"
        )
        self.assertEqual(
            thumb_hash,
            expected_hash,
            f"PDF looks different. Check if {converted} looks weird.",
        )

    # Only run if convert is available
    @pytest.mark.skipif(
        "PAPERLESS_TEST_SKIP_CONVERT" in os.environ,
        reason="PAPERLESS_TEST_SKIP_CONVERT set, skipping Test",
    )
    @mock.patch("documents.loggers.LoggingMixin.log")  # Disable log output
    def test_generate_pdf_from_html(self, m):
        # TODO
        class MailAttachmentMock:
            def __init__(self, payload, content_id):
                self.payload = payload
                self.content_id = content_id

        result = None

        with open(os.path.join(self.SAMPLE_FILES, "sample.html")) as html_file:
            with open(os.path.join(self.SAMPLE_FILES, "sample.png"), "rb") as png_file:
                html = html_file.read()
                png = png_file.read()
                attachments = [
                    MailAttachmentMock(png, "part1.pNdUSz0s.D3NqVtPg@example.de"),
                ]
                result = self.parser.generate_pdf_from_html(html, attachments)

        pdf_path = os.path.join(self.parser.tempdir, "test_generate_pdf_from_html.pdf")

        with open(pdf_path, "wb") as file:
            file.write(result)
            file.close()

        converted = os.path.join(parser.tempdir, "test_generate_pdf_from_html.webp")
        run_convert(
            density=300,
            scale="500x5000>",
            alpha="remove",
            strip=True,
            trim=False,
            auto_orient=True,
            input_file=f"{pdf_path}",  # Do net define an index to convert all pages.
            output_file=converted,
            logging_group=None,
        )
        self.assertTrue(os.path.isfile(converted))
        thumb_hash = self.hashfile(converted)

        # The created pdf is not reproducible. But the converted image should always look the same.
        expected_hash = (
            "267d61f0ab8f128a037002a424b2cb4bfe18a81e17f0b70f15d241688ed47d1a"
        )
        self.assertEqual(
            thumb_hash,
            expected_hash,
            f"PDF looks different. Check if {converted} looks weird. "
            f"If Rick Astley is shown, Gotenberg loads from web which is bad for Mail content.",
        )

    @staticmethod
    def test_is_online_image_still_available():
        """
        A public image is used in the html sample file. We have no control
        whether this image stays online forever, so here we check if it is still there
        """

        # Start by Testing if nonexistent URL really throws an Exception
        with pytest.raises(HTTPError):
            urlopen("https://upload.wikimedia.org/wikipedia/en/f/f7/nonexistent.png")

        # Now check the URL used in samples/sample.html
        urlopen("https://upload.wikimedia.org/wikipedia/en/f/f7/RickRoll.png")
