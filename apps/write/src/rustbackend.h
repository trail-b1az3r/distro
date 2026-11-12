#pragma once

#include <QJsonObject>
#include <QJsonValue>

// Small Qt process transport. All application behavior belongs in Rust.
class RustBackend
{
public:
    static bool request(const QJsonObject &request, QJsonValue *result = nullptr);
};
