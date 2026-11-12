#include "rustbackend.h"

#include <QFileInfo>
#include <QJsonDocument>
#include <QProcess>

bool RustBackend::request(const QJsonObject &request, QJsonValue *result)
{
    QString program = qEnvironmentVariable("NEXORA_WRITE_BACKEND");
    if (program.isEmpty())
        program = QString::fromUtf8(HELPER_DIR) + QStringLiteral("/nexora-write-backend");
    if (!QFileInfo(program).isExecutable())
        return false;

    // QML calls are serialized on the GUI thread; one persistent worker keeps
    // the JSON-lines request/reply transport cheap and ordered.
    static QProcess process;
    static QByteArray buffer;
    if (process.state() == QProcess::NotRunning) {
        buffer.clear();
        process.setProgram(program);
        process.setProcessChannelMode(QProcess::SeparateChannels);
        process.start();
        if (!process.waitForStarted(1500))
            return false;
    }

    const QByteArray payload = QJsonDocument(request).toJson(QJsonDocument::Compact) + '\n';
    if (process.write(payload) != payload.size())
        return false;
    process.waitForBytesWritten(1500);

    int newline = buffer.indexOf('\n');
    while (newline < 0) {
        if (!process.waitForReadyRead(6000)) {
            if (process.state() == QProcess::NotRunning)
                buffer.clear();
            return false;
        }
        buffer += process.readAllStandardOutput();
        newline = buffer.indexOf('\n');
    }

    const QByteArray line = buffer.left(newline);
    buffer.remove(0, newline + 1);
    const QJsonObject response = QJsonDocument::fromJson(line).object();
    if (!response.value("ok").toBool())
        return false;
    if (result)
        *result = response.value("result");
    return true;
}
