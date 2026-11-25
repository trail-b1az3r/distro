#pragma once
// MDXL in Word documents. Write's .docx export turns MDXL's text styles (bold, italic, underline, bigger and smaller
// text, colours, badges, gradients, tooltips, ruby) into Word runs, and its ::: blocks (columns, cards, timelines,
// chats) and centred lines into paragraphs that look like them. Only QtCore, so it is tested on its own.
#include <QString>

namespace MdxlWord {

// Text for WordprocessingML: &, < and > escaped.
QString escapeXml(QString s);

// Word runs (<w:r>…</w:r>) for one line of MDXL.
QString runs(const QString &line);

// Word paragraphs and tables (what goes inside <w:body>, before its <w:sectPr>) for a whole MDXL document.
QString body(const QString &text);

}
