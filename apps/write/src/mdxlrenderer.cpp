#include "mdxlrenderer.h"

#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>

static QString helperPath()
{
    const QString env = qEnvironmentVariable("WRITE_MDXL_RENDER");
    return env.isEmpty() ? QStringLiteral(HELPER_DIR "/mdxl-render") : env;
}

MdxlRenderer::MdxlRenderer(QObject *parent) : QObject(parent)
{
    m_debounce.setSingleShot(true);
    m_debounce.setInterval(250);
    connect(&m_debounce, &QTimer::timeout, this, &MdxlRenderer::send);
    connect(&m_proc, &QProcess::readyReadStandardOutput, this, &MdxlRenderer::readAnswers);
    connect(&m_proc, &QProcess::finished, this, [this](int code) {
        if (code != 0 && m_error.isEmpty())
            setError(tr("The MDXL renderer stopped (exit %1).").arg(code));
    });
}

MdxlRenderer::~MdxlRenderer()
{
    m_proc.closeWriteChannel();
    if (!m_proc.waitForFinished(500))
        m_proc.kill();
}

void MdxlRenderer::start()
{
    if (m_proc.state() != QProcess::NotRunning)
        return;
    const QString helper = helperPath();
    if (!QFileInfo(helper).isExecutable()) {
        setError(tr("The MDXL renderer is missing (%1).").arg(helper));
        return;
    }
    m_proc.setProgram(helper);
    m_proc.setProcessChannelMode(QProcess::SeparateChannels);
    m_proc.start();
}

void MdxlRenderer::render(const QString &text, bool now)
{
    m_pending = text;
    if (now)
        send();
    else
        m_debounce.start();
}

void MdxlRenderer::send()
{
    m_debounce.stop();
    start();
    if (m_proc.state() == QProcess::NotRunning)
        return;
    const QJsonObject req{{"id", ++m_id}, {"text", m_pending}};
    m_proc.write(QJsonDocument(req).toJson(QJsonDocument::Compact) + '\n');
}

void MdxlRenderer::readAnswers()
{
    m_buffer += m_proc.readAllStandardOutput();
    int nl;
    while ((nl = m_buffer.indexOf('\n')) >= 0) {
        const QByteArray line = m_buffer.left(nl);
        m_buffer.remove(0, nl + 1);
        const QJsonObject ans = QJsonDocument::fromJson(line).object();
        if (ans.contains("error")) {
            setError(ans.value("error").toString());
            continue;
        }
        if (ans.value("id").toInteger() != m_id)
            continue;  // an older version of the text; a newer one is on its way
        m_raw = ans.value("html").toString();
        setError(QString());
        emit htmlChanged();
    }
}

QString MdxlRenderer::html() const
{
    if (m_raw.isEmpty())
        return {};
    // The theme's colours after MDXL's own stylesheet, so they win.
    const QString style = QStringLiteral("<style>%1</style>").arg(m_css);
    QString out = m_raw;
    const int head = out.indexOf(QLatin1String("</head>"), 0, Qt::CaseInsensitive);
    return head >= 0 ? out.insert(head, style) : style + out;
}

void MdxlRenderer::setCss(const QString &css)
{
    if (css == m_css)
        return;
    m_css = css;
    emit htmlChanged();
}

void MdxlRenderer::setError(const QString &e)
{
    if (e == m_error)
        return;
    m_error = e;
    emit errorChanged();
}
