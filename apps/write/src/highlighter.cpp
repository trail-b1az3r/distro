#include "highlighter.h"

#include "spelling.h"

#include <KSyntaxHighlighting/Definition>
#include <KSyntaxHighlighting/Repository>
#include <KSyntaxHighlighting/SyntaxHighlighter>
#include <KSyntaxHighlighting/Theme>
#include <QColor>
#include <QRegularExpression>
#include <QTextCharFormat>
#include <QTextDocument>

using namespace KSyntaxHighlighting;

namespace {

// KDE's syntax colours, then misspelled words underlined on top of them: a document has one highlighter, so the
// spelling is drawn by the same one. Inline code, links and indented code are not checked.
class SpellingHighlighter : public SyntaxHighlighter
{
public:
    using SyntaxHighlighter::SyntaxHighlighter;

protected:
    void highlightBlock(const QString &text) override
    {
        SyntaxHighlighter::highlightBlock(text);
        Spelling *spelling = Spelling::instance();
        if (!spelling->enabled() || !spelling->available() || text.startsWith(QLatin1String("    "))
            || text.startsWith(QLatin1Char('\t')))
            return;
        static const QRegularExpression skip(QStringLiteral("`[^`]*`|\\b[a-z][a-z0-9+.-]*://\\S+|\\]\\([^)]*\\)|<[^>]*>"));
        static const QRegularExpression word(QStringLiteral("\\p{L}[\\p{L}'\\x{2019}]*"));
        QList<QPair<qsizetype, qsizetype>> skipped;
        for (auto it = skip.globalMatch(text); it.hasNext();) {
            const auto m = it.next();
            skipped.append({m.capturedStart(), m.capturedEnd()});
        }
        for (auto it = word.globalMatch(text); it.hasNext();) {
            const auto m = it.next();
            QString w = m.captured();
            while (w.endsWith(QLatin1Char('\'')) || w.endsWith(QChar(0x2019)))
                w.chop(1);
            const qsizetype start = m.capturedStart();
            bool inSkipped = false;
            for (const auto &range : skipped)
                inSkipped = inSkipped || (start >= range.first && start < range.second);
            if (inSkipped || !spelling->isMisspelled(w))
                continue;
            for (qsizetype i = start; i < start + w.size(); ++i) {
                QTextCharFormat f = format(int(i));
                f.setUnderlineStyle(QTextCharFormat::SpellCheckUnderline);
                f.setUnderlineColor(QColor(0xE5, 0x48, 0x4D));
                setFormat(int(i), 1, f);
            }
        }
    }
};

} // namespace

Highlighter::Highlighter(QObject *parent) : QObject(parent)
{
    // Spelling switched on or off, a word added or ignored: drawn again.
    connect(Spelling::instance(), &Spelling::changed, this, [this] {
        if (m_highlighter)
            m_highlighter->rehighlight();
    });
}
Highlighter::~Highlighter() = default;

Repository &Highlighter::repository()
{
    static Repository repo;
    return repo;
}

void Highlighter::setDocument(QQuickTextDocument *d)
{
    if (d == m_document)
        return;
    m_document = d;
    delete m_highlighter;
    m_highlighter = d ? new SpellingHighlighter(d->textDocument()) : nullptr;
    apply();
}

void Highlighter::setDark(bool d)
{
    if (d == m_dark)
        return;
    m_dark = d;
    apply();
}

void Highlighter::setFileName(const QString &f)
{
    if (f == m_fileName)
        return;
    m_fileName = f;
    apply();
}

void Highlighter::apply()
{
    if (m_highlighter) {
        Repository &repo = repository();
        Definition def;
        if (m_fileName.endsWith(QLatin1String(".txt")))
            def = Definition();
        else if (!m_fileName.endsWith(QLatin1String(".md")))
            def = repo.definitionForName(QStringLiteral("Markdown Extended Logic"));
        if (!def.isValid() && !m_fileName.endsWith(QLatin1String(".txt")))
            def = repo.definitionForName(QStringLiteral("Markdown"));
        m_highlighter->setTheme(repo.defaultTheme(m_dark ? Repository::DarkTheme : Repository::LightTheme));
        m_highlighter->setDefinition(def);
        m_highlighter->rehighlight();
        m_definition = def.isValid() ? def.name() : QStringLiteral("Plain text");
    }
    emit changed();
}
