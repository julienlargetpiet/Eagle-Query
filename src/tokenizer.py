import re
from html.parser import HTMLParser

class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def extract_text(content, content_type):
    if content_type in ("text/html", "text/xml"):
        parser = VisibleText()
        parser.feed(content)
        return " ".join(parser.parts)

    return content  

def tokenize(text):
    for match in re.finditer(r"[^\W_]+", text.casefold()):
        word = match.group()

        if len(word) <= 64:
            yield word


