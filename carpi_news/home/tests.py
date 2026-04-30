from unittest.mock import patch

from django.test import SimpleTestCase

from home.content_polisher import content_polisher
from home.universal_news_monitor import parse_ai_article_json


class AIArticleParsingTests(SimpleTestCase):
    def test_parse_loose_json_with_multiline_content_and_quotes(self):
        response = '''{
  "titolo": "Borse di studio ER.GO, copertura totale",
  "sommario": "Tutti gli studenti idonei riceveranno la borsa di studio.",
  "contenuto": "
Tutti gli studenti idonei riceveranno la borsa.

De Lillo: "Una vittoria collettiva, non un caso"

Il risultato arriva dopo mesi di tensione.
",
  "tags": ["Diritto allo studio", "ER.GO"]
}'''

        parsed = parse_ai_article_json(response)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["titolo"], "Borse di studio ER.GO, copertura totale")
        self.assertEqual(parsed["sommario"], "Tutti gli studenti idonei riceveranno la borsa di studio.")
        self.assertIn('De Lillo: "Una vittoria collettiva, non un caso"', parsed["contenuto"])
        self.assertEqual(parsed["tags"], ["Diritto allo studio", "ER.GO"])

    def test_polisher_converts_literal_escaped_newlines(self):
        with patch.object(content_polisher, "add_internal_links", side_effect=lambda content, **kwargs: content):
            polished = content_polisher.polish_article({
                "titolo": "Titolo prova",
                "contenuto": "Primo paragrafo.\\n\\nSottotitolo\\n\\nSecondo paragrafo.",
                "sommario": "Riga uno.\\n\\nRiga due.",
            })

        self.assertIn("<p>Primo paragrafo.</p>", polished["contenuto"])
        self.assertIn("<p>Secondo paragrafo.</p>", polished["contenuto"])
        self.assertNotIn("\\n", polished["contenuto"])
        self.assertNotIn("\\n", polished["sommario"])
