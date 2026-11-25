#include "mdxlword.h"

#include <QList>
#include <QRegularExpression>
#include <QStringList>
#include <algorithm>

namespace {

// A run's look. Word wants a run's properties in its schema's order, so they are kept apart and written in that order.
struct Look {
    bool bold = false, italic = false, strike = false, mono = false;
    QString color, underline, fill;
    int size = 0;   // half-points; 0 is the document's own

    QString xml() const
    {
        QString p;
        if (mono)
            p += QStringLiteral("<w:rFonts w:ascii=\"Consolas\" w:hAnsi=\"Consolas\" w:cs=\"Consolas\"/>");
        if (bold)
            p += QStringLiteral("<w:b/>");
        if (italic)
            p += QStringLiteral("<w:i/>");
        if (strike)
            p += QStringLiteral("<w:strike/>");
        if (!color.isEmpty())
            p += QStringLiteral("<w:color w:val=\"%1\"/>").arg(color);
        if (size)
            p += QStringLiteral("<w:sz w:val=\"%1\"/>").arg(size);
        if (!underline.isEmpty())
            p += QStringLiteral("<w:u w:val=\"%1\"/>").arg(underline);
        if (!fill.isEmpty())
            p += QStringLiteral("<w:shd w:val=\"clear\" w:color=\"auto\" w:fill=\"%1\"/>").arg(fill);
        return p.isEmpty() ? QString() : QStringLiteral("<w:rPr>") + p + QStringLiteral("</w:rPr>");
    }
};

QString run(const QString &text, const Look &look)
{
    if (text.isEmpty())
        return {};
    return QStringLiteral("<w:r>") + look.xml() + QStringLiteral("<w:t xml:space=\"preserve\">")
           + MdxlWord::escapeXml(text) + QStringLiteral("</w:t></w:r>");
}

struct Rgb { int r, g, b; };

Rgb rgb(const QString &hex)   // "RRGGBB"
{
    const uint v = hex.toUInt(nullptr, 16);
    return {int(v >> 16 & 0xff), int(v >> 8 & 0xff), int(v & 0xff)};
}

// Black or white, whichever reads better on a colour (as MDXL's badges do).
QString readableOn(const QString &hex)
{
    const Rgb c = rgb(hex);
    const double luminance = (0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b) / 255.0;
    return luminance > 0.55 ? QStringLiteral("111111") : QStringLiteral("FFFFFF");
}

QString runsWith(const QString &line, const Look &base);

// The inline tokens, earliest first. Each is a pattern and what it becomes.
struct Token {
    QRegularExpression re;
    QString (*make)(const QRegularExpressionMatch &, const Look &);
};

QString styled(const QRegularExpressionMatch &m, const Look &base, void (*apply)(Look &))
{
    Look look = base;
    apply(look);
    return runsWith(m.captured(1), look);
}

const QList<Token> &tokens()
{
    static const QList<Token> list = {
        {QRegularExpression(QStringLiteral("`([^`]+)`")),
         [](const QRegularExpressionMatch &m, const Look &base) {
             Look look = base;   // code is shown as written
             look.mono = true;
             return run(m.captured(1), look);
         }},
        {QRegularExpression(QStringLiteral("/u//(.+?)/u//")),
         [](const QRegularExpressionMatch &m, const Look &b) { return styled(m, b, [](Look &l) { l.underline = QStringLiteral("single"); }); }},
        {QRegularExpression(QStringLiteral("/big//(.+?)/big//")),
         [](const QRegularExpressionMatch &m, const Look &b) { return styled(m, b, [](Look &l) { l.bold = true; l.size = 32; }); }},
        {QRegularExpression(QStringLiteral("/sml//(.+?)/sml//")),
         [](const QRegularExpressionMatch &m, const Look &b) { return styled(m, b, [](Look &l) { l.size = 17; l.color = QStringLiteral("5F6368"); }); }},
        {QRegularExpression(QStringLiteral("/bdg(?:#([0-9A-Fa-f]{6}))?//(.+?)/bdg//")),
         [](const QRegularExpressionMatch &m, const Look &base) {
             Look look = base;
             look.bold = true;
             look.size = 18;
             look.fill = m.captured(1).isEmpty() ? QStringLiteral("E1ECD8") : m.captured(1).toUpper();
             look.color = m.captured(1).isEmpty() ? QStringLiteral("202124") : readableOn(m.captured(1));
             return run(QLatin1Char(' ') + m.captured(2) + QLatin1Char(' '), look);
         }},
        {QRegularExpression(QStringLiteral("/grad#([0-9A-Fa-f]{6})#([0-9A-Fa-f]{6})//(.+?)/grad//")),
         [](const QRegularExpressionMatch &m, const Look &base) {
             // A colour a letter, from the first to the second.
             const Rgb from = rgb(m.captured(1)), to = rgb(m.captured(2));
             const QString text = m.captured(3);
             const qsizetype last = std::max<qsizetype>(1, text.size() - 1);
             QString out;
             for (qsizetype i = 0; i < text.size(); ++i) {
                 const double t = text.size() == 1 ? 0.0 : double(i) / double(last);
                 const auto mix = [t](int a, int b) { return int(a + (b - a) * t + 0.5); };
                 Look look = base;
                 look.bold = true;
                 look.color = QStringLiteral("%1%2%3")
                                  .arg(mix(from.r, to.r), 2, 16, QLatin1Char('0'))
                                  .arg(mix(from.g, to.g), 2, 16, QLatin1Char('0'))
                                  .arg(mix(from.b, to.b), 2, 16, QLatin1Char('0'))
                                  .toUpper();
                 out += run(text.mid(i, 1), look);
             }
             return out;
         }},
        {QRegularExpression(QStringLiteral("/wave//(.+?)/wave//")),
         [](const QRegularExpressionMatch &m, const Look &b) { return styled(m, b, [](Look &l) { l.italic = true; }); }},
        {QRegularExpression(QStringLiteral("/glow//(.+?)/glow//")),
         [](const QRegularExpressionMatch &m, const Look &b) {
             return styled(m, b, [](Look &l) { l.bold = true; l.color = QStringLiteral("5F8F2E"); });
         }},
        {QRegularExpression(QStringLiteral("/tip//(.+?)//(.+?)/tip//")),
         [](const QRegularExpressionMatch &m, const Look &base) {
             // Paper has no hover: the tooltip follows in brackets.
             Look text = base, tip = base;
             text.underline = QStringLiteral("dotted");
             tip.size = 17;
             tip.color = QStringLiteral("5F6368");
             return runsWith(m.captured(1), text) + run(QStringLiteral(" (") + m.captured(2) + QLatin1Char(')'), tip);
         }},
        {QRegularExpression(QStringLiteral("/rb//(.+?)//(.+?)/rb//")),
         [](const QRegularExpressionMatch &m, const Look &base) {
             const QString look = base.xml();
             return QStringLiteral("<w:r>") + look + QStringLiteral(
                        "<w:ruby><w:rubyPr><w:rubyAlign w:val=\"center\"/><w:hps w:val=\"11\"/><w:hpsRaise w:val=\"20\"/>"
                        "<w:hpsBaseText w:val=\"22\"/><w:lid w:val=\"ja-JP\"/></w:rubyPr><w:rt><w:r>")
                    + look + QStringLiteral("<w:t>") + MdxlWord::escapeXml(m.captured(2))
                    + QStringLiteral("</w:t></w:r></w:rt><w:rubyBase><w:r>") + look + QStringLiteral("<w:t>")
                    + MdxlWord::escapeXml(m.captured(1)) + QStringLiteral("</w:t></w:r></w:rubyBase></w:ruby></w:r>");
         }},
        {QRegularExpression(QStringLiteral("/col//(.*?)\\s*/col#([0-9A-Fa-f]{6})//")),
         [](const QRegularExpressionMatch &m, const Look &base) {
             Look look = base;
             look.color = m.captured(2).toUpper();
             return runsWith(m.captured(1), look);
         }},
        {QRegularExpression(QStringLiteral("\\[([^\\]]+)\\]\\(([^)\\s]+)\\)")),
         [](const QRegularExpressionMatch &m, const Look &b) {
             return styled(m, b, [](Look &l) { l.underline = QStringLiteral("single"); l.color = QStringLiteral("315FBA"); });
         }},
        {QRegularExpression(QStringLiteral("\\*\\*(.+?)\\*\\*")),
         [](const QRegularExpressionMatch &m, const Look &b) { return styled(m, b, [](Look &l) { l.bold = true; }); }},
        {QRegularExpression(QStringLiteral("~~(.+?)~~")),
         [](const QRegularExpressionMatch &m, const Look &b) { return styled(m, b, [](Look &l) { l.strike = true; }); }},
        {QRegularExpression(QStringLiteral("(?<![*\\w])\\*(?![\\s*])(.+?)(?<!\\s)\\*(?!\\*)")),
         [](const QRegularExpressionMatch &m, const Look &b) { return styled(m, b, [](Look &l) { l.italic = true; }); }},
    };
    return list;
}

QString runsWith(const QString &line, const Look &base)
{
    QString out;
    qsizetype pos = 0;
    while (pos < line.size()) {
        // The token that starts first (the earlier one in the list when two start together).
        const Token *best = nullptr;
        QRegularExpressionMatch bestMatch;
        for (const Token &token : tokens()) {
            const auto m = token.re.match(line, pos);
            if (m.hasMatch() && (!best || m.capturedStart() < bestMatch.capturedStart())) {
                best = &token;
                bestMatch = m;
            }
        }
        if (!best) {
            out += run(line.mid(pos), base);
            break;
        }
        out += run(line.mid(pos, bestMatch.capturedStart() - pos), base);
        out += best->make(bestMatch, base);
        pos = bestMatch.capturedEnd();
    }
    return out;
}

// A paragraph's look, written in the schema's order too.
struct Para {
    QString style, jc, fill, leftBorder, topBorder;
    int indent = 0;
    bool pageBreakBefore = false;

    QString xml(const QString &runs) const
    {
        QString p;
        if (!style.isEmpty())
            p += QStringLiteral("<w:pStyle w:val=\"%1\"/>").arg(style);
        if (pageBreakBefore)
            p += QStringLiteral("<w:pageBreakBefore/>");
        if (!leftBorder.isEmpty() || !topBorder.isEmpty()) {
            p += QStringLiteral("<w:pBdr>");
            if (!topBorder.isEmpty())
                p += QStringLiteral("<w:top w:val=\"dotted\" w:sz=\"6\" w:space=\"6\" w:color=\"%1\"/>").arg(topBorder);
            if (!leftBorder.isEmpty())
                p += QStringLiteral("<w:left w:val=\"single\" w:sz=\"18\" w:space=\"8\" w:color=\"%1\"/>").arg(leftBorder);
            p += QStringLiteral("</w:pBdr>");
        }
        if (!fill.isEmpty())
            p += QStringLiteral("<w:shd w:val=\"clear\" w:color=\"auto\" w:fill=\"%1\"/>").arg(fill);
        if (indent)
            p += QStringLiteral("<w:ind w:left=\"%1\"/>").arg(indent);
        if (!jc.isEmpty())
            p += QStringLiteral("<w:jc w:val=\"%1\"/>").arg(jc);
        return QStringLiteral("<w:p>") + (p.isEmpty() ? QString() : QStringLiteral("<w:pPr>") + p + QStringLiteral("</w:pPr>"))
               + runs + QStringLiteral("</w:p>");
    }
};

QString tableXml(const QList<QStringList> &rows)
{
    QString out = QStringLiteral("<w:tbl><w:tblPr><w:tblBorders>"
                                 "<w:top w:val=\"single\" w:sz=\"4\"/><w:left w:val=\"single\" w:sz=\"4\"/>"
                                 "<w:bottom w:val=\"single\" w:sz=\"4\"/><w:right w:val=\"single\" w:sz=\"4\"/>"
                                 "<w:insideH w:val=\"single\" w:sz=\"4\"/><w:insideV w:val=\"single\" w:sz=\"4\"/>"
                                 "</w:tblBorders></w:tblPr>");
    for (const QStringList &cells : rows) {
        out += QStringLiteral("<w:tr>");
        for (const QString &cell : cells)
            out += QStringLiteral("<w:tc><w:tcPr><w:tcW w:w=\"2400\" w:type=\"dxa\"/></w:tcPr><w:p>") + MdxlWord::runs(cell)
                   + QStringLiteral("</w:p></w:tc>");
        out += QStringLiteral("</w:tr>");
    }
    return out + QStringLiteral("</w:tbl>");
}

} // namespace

QString MdxlWord::escapeXml(QString s)
{
    s.replace(QLatin1Char('&'), QStringLiteral("&amp;"));
    s.replace(QLatin1Char('<'), QStringLiteral("&lt;"));
    s.replace(QLatin1Char('>'), QStringLiteral("&gt;"));
    return s;
}

QString MdxlWord::runs(const QString &line)
{
    return runsWith(line, Look());
}

QString MdxlWord::body(const QString &text)
{
    static const QRegularExpression open(QStringLiteral("^:::[ \\t]*(columns|card|timeline|chat)\\b[ \\t]*(.*?)[ \\t]*$"));
    static const QRegularExpression split(QStringLiteral("^:::\\|[ \\t]*$"));
    static const QRegularExpression close(QStringLiteral("^:::[ \\t]*$"));
    static const QRegularExpression centred(QStringLiteral("^[ \\t]*->[ \\t]*(.+?)[ \\t]*<-[ \\t]*$"));
    static const QRegularExpression when(QStringLiteral("^(.{1,40}?)[ \\t]+::[ \\t]+(.*)$"));
    static const QRegularExpression speaker(QStringLiteral("^([^:]{1,40}):[ \\t]+(.*)$"));
    static const QRegularExpression fence(QStringLiteral("^[ \\t]*(`{3,}|~{3,})"));

    QString out;
    QStringList blocks;          // the ::: blocks the line is in, outermost first
    QStringList firstSpeaker;    // each open chat's first speaker (their messages on the left)
    QString inFence;             // the fence a code block opened with, while in one
    const QStringList lines = text.split(QLatin1Char('\n'));
    for (qsizetype i = 0; i < lines.size(); ++i) {
        const QString line = lines[i];
        const QString trimmed = line.trimmed();
        const bool inCard = blocks.contains(QStringLiteral("card"));
        Para para;
        if (inCard) {
            para.fill = QStringLiteral("F6F7F4");
            para.leftBorder = QStringLiteral("5F8F2E");
        }

        // Code is shown as written, in a monospaced font.
        const auto fenceMatch = fence.match(line);
        if (!inFence.isEmpty()) {
            if (fenceMatch.hasMatch() && fenceMatch.captured(1).at(0) == inFence.at(0)
                && fenceMatch.captured(1).size() >= inFence.size()) {
                inFence.clear();
                continue;
            }
            Look mono;
            mono.mono = true;
            para.fill = QStringLiteral("F1F3F4");
            out += para.xml(run(line, mono));
            continue;
        }
        if (fenceMatch.hasMatch()) {
            inFence = fenceMatch.captured(1);
            continue;
        }

        if (trimmed == QLatin1String("<!-- WRITE_PAGE_BREAK -->")) {
            out += QStringLiteral("<w:p><w:r><w:br w:type=\"page\"/></w:r></w:p>");
            continue;
        }

        // ::: blocks.
        const auto opened = open.match(line);
        if (opened.hasMatch()) {
            const QString kind = opened.captured(1);
            blocks << kind;
            if (kind == QLatin1String("chat"))
                firstSpeaker << QString();
            if (kind == QLatin1String("card")) {
                Para title;
                title.fill = QStringLiteral("F6F7F4");
                title.leftBorder = QStringLiteral("5F8F2E");
                Look bold;
                bold.bold = true;
                if (!opened.captured(2).isEmpty())
                    out += title.xml(runsWith(opened.captured(2), bold));
            }
            continue;
        }
        if (!blocks.isEmpty() && split.match(line).hasMatch()) {
            Para rule;
            rule.topBorder = QStringLiteral("9AA0A6");
            out += rule.xml(QString());
            continue;
        }
        if (!blocks.isEmpty() && close.match(line).hasMatch()) {
            if (blocks.takeLast() == QLatin1String("chat") && !firstSpeaker.isEmpty())
                firstSpeaker.removeLast();
            continue;
        }

        // Tables: header, separator and rows.
        if (trimmed.startsWith(QLatin1Char('|')) && trimmed.endsWith(QLatin1Char('|')) && trimmed.size() > 1) {
            QList<QStringList> rows;
            while (i < lines.size()) {
                const QString row = lines[i].trimmed();
                if (!(row.startsWith(QLatin1Char('|')) && row.endsWith(QLatin1Char('|')) && row.size() > 1))
                    break;
                QStringList cells = row.mid(1, row.size() - 2).split(QLatin1Char('|'));
                for (QString &cell : cells)
                    cell = cell.trimmed();
                const bool separator = std::all_of(cells.cbegin(), cells.cend(), [](const QString &v) {
                    QString rest = v;
                    rest.remove(QLatin1Char('-'));
                    rest.remove(QLatin1Char(':'));
                    return !v.isEmpty() && rest.trimmed().isEmpty();
                });
                if (!separator)
                    rows << cells;
                ++i;
            }
            --i;
            if (!rows.isEmpty())
                out += tableXml(rows);
            continue;
        }

        const QString inner = blocks.isEmpty() ? QString() : blocks.last();
        if (inner == QLatin1String("timeline") && !trimmed.isEmpty()) {
            // When, in blue and bold, then what.
            para.leftBorder = QStringLiteral("C9CFC2");
            para.indent = 240;
            const auto m = when.match(trimmed);
            Look date;
            date.bold = true;
            date.color = QStringLiteral("315FBA");
            out += para.xml(m.hasMatch() ? run(m.captured(1), date) + run(QStringLiteral("  "), Look()) + runs(m.captured(2))
                                         : runs(trimmed));
            continue;
        }
        if (inner == QLatin1String("chat") && !trimmed.isEmpty()) {
            // The first speaker on the left, everyone else on the right, each on a tinted line.
            const auto m = speaker.match(trimmed);
            QString name = m.hasMatch() ? m.captured(1).trimmed() : QString();
            if (!name.isEmpty() && !firstSpeaker.isEmpty() && firstSpeaker.last().isEmpty())
                firstSpeaker.last() = name;
            const bool left = name.isEmpty() || firstSpeaker.isEmpty() || name == firstSpeaker.last();
            para.fill = left ? QStringLiteral("EEF0EC") : QStringLiteral("E1ECD8");
            para.leftBorder.clear();
            para.jc = left ? QStringLiteral("left") : QStringLiteral("right");
            Look who;
            who.bold = true;
            who.color = QStringLiteral("5F6368");
            out += para.xml(m.hasMatch() ? run(name + QStringLiteral(": "), who) + runs(m.captured(2)) : runs(trimmed));
            continue;
        }

        // Headings, centred lines and the rest.
        QString value = line;
        int level = 0;
        while (level < value.size() && level < 6 && value[level] == QLatin1Char('#'))
            ++level;
        if (level && level < value.size() && value[level] == QLatin1Char(' '))
            value = value.mid(level + 1);
        else
            level = 0;
        if (level)
            para.style = QStringLiteral("Heading%1").arg(level);
        const auto centre = centred.match(value);
        if (centre.hasMatch()) {
            para.jc = QStringLiteral("center");
            value = centre.captured(1);
        }
        if (inCard && value.trimmed().isEmpty())
            continue;   // a card's blank lines would split its tint
        // Headings are bold and bigger themselves too, for apps that do not know Word's heading styles.
        static const int headingSizes[] = {0, 40, 32, 28, 24, 22, 22};
        Look heading;
        heading.bold = level > 0;
        heading.size = headingSizes[level];
        out += para.xml(runsWith(value, heading));
    }
    return out;
}
