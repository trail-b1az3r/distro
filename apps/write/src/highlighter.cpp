#include "highlighter.h"

#include <KSyntaxHighlighting/Definition>
#include <KSyntaxHighlighting/Repository>
#include <KSyntaxHighlighting/SyntaxHighlighter>
#include <KSyntaxHighlighting/Theme>
#include <QTextDocument>

using namespace KSyntaxHighlighting;

Highlighter::Highlighter(QObject *parent) : QObject(parent) {}
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
    m_highlighter = d ? new SyntaxHighlighter(d->textDocument()) : nullptr;
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
