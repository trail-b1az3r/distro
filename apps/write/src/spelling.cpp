#include "spelling.h"

#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QJSEngine>
#include <QQmlEngine>
#include <QSettings>
#include <QStandardPaths>
#include <QTextStream>
#include <Sonnet/Speller>

Spelling *Spelling::s_instance = nullptr;

Spelling::Spelling(QObject *parent) : QObject(parent), m_speller(new Sonnet::Speller())
{
    const QSettings saved(QStringLiteral(APP_ID), QStringLiteral("write"));
    m_enabled = saved.value(QStringLiteral("spelling/enabled"), true).toBool();
    m_autocorrect = saved.value(QStringLiteral("spelling/autocorrect"), true).toBool();
    // Sonnet picks the language from the system's locale; a dictionary for it may be missing, English then.
    if (!m_speller->isValid() || !m_speller->availableLanguages().contains(m_speller->language())) {
        const QStringList langs = m_speller->availableLanguages();
        for (const QString &fallback : {QStringLiteral("en_US"), QStringLiteral("en_GB"), QStringLiteral("en")}) {
            if (langs.contains(fallback)) {
                m_speller->setLanguage(fallback);
                break;
            }
        }
    }
    loadCorrections();
}

Spelling::~Spelling()
{
    delete m_speller;
    if (s_instance == this)
        s_instance = nullptr;
}

Spelling *Spelling::instance()
{
    if (!s_instance)
        s_instance = new Spelling(QCoreApplication::instance());
    return s_instance;
}

Spelling *Spelling::create(QQmlEngine *, QJSEngine *)
{
    Spelling *spelling = instance();
    QJSEngine::setObjectOwnership(spelling, QJSEngine::CppOwnership);
    return spelling;
}

void Spelling::setEnabled(bool on)
{
    if (on == m_enabled)
        return;
    m_enabled = on;
    QSettings(QStringLiteral(APP_ID), QStringLiteral("write")).setValue(QStringLiteral("spelling/enabled"), on);
    emit changed();
}

void Spelling::setAutocorrect(bool on)
{
    if (on == m_autocorrect)
        return;
    m_autocorrect = on;
    QSettings(QStringLiteral(APP_ID), QStringLiteral("write")).setValue(QStringLiteral("spelling/autocorrect"), on);
    emit changed();
}

bool Spelling::available() const
{
    return m_speller->isValid() && !m_speller->availableLanguages().isEmpty();
}

QString Spelling::language() const
{
    return available() ? m_speller->language() : QString();
}

bool Spelling::checkable(const QString &word)
{
    if (word.size() < 2)
        return false;
    bool lower = false;
    for (const QChar c : word) {
        if (!c.isLetter() && c != QLatin1Char('\'') && c != QChar(0x2019))
            return false;
        if (c.isLower())
            lower = true;
    }
    return lower;   // ALL CAPS: an acronym, left alone
}

bool Spelling::isMisspelled(const QString &word) const
{
    if (!m_enabled || !available() || !checkable(word) || m_ignored.contains(word))
        return false;
    QString w = word;
    w.replace(QChar(0x2019), QLatin1Char('\''));
    return m_speller->isMisspelled(w);
}

QStringList Spelling::suggestions(const QString &word, int max) const
{
    if (!available())
        return {};
    QStringList out = m_speller->suggest(word);
    if (out.size() > max)
        out = out.mid(0, max);
    return out;
}

void Spelling::addToDictionary(const QString &word)
{
    if (available())
        m_speller->addToPersonal(word);
    emit changed();
}

void Spelling::ignore(const QString &word)
{
    m_ignored.insert(word);
    if (available())
        m_speller->addToSession(word);
    emit changed();
}

QString Spelling::matchCase(const QString &typed, const QString &fix)
{
    if (typed.isEmpty() || fix.isEmpty())
        return fix;
    if (typed.size() > 1 && typed == typed.toUpper())
        return fix.toUpper();
    if (typed.at(0).isUpper())
        return fix.at(0).toUpper() + fix.mid(1);
    return fix;
}

QString Spelling::correction(const QString &word) const
{
    if (!m_autocorrect || word.isEmpty())
        return {};
    if (word == QLatin1String("i"))
        return QStringLiteral("I");
    const QString key = word.toLower();
    const auto it = m_corrections.constFind(key);
    if (it != m_corrections.constEnd())
        return matchCase(word, it.value());
    // TWo INitial CApitals: a word of 3+ letters, the first two capital, the rest lower case.
    if (word.size() >= 3 && word.at(0).isUpper() && word.at(1).isUpper()) {
        bool restLower = true;
        for (int i = 2; i < word.size(); ++i)
            restLower = restLower && word.at(i).isLower();
        if (restLower)
            return word.at(0) + word.mid(1).toLower();
    }
    return {};
}

void Spelling::loadCorrections()
{
    const QString own = QStandardPaths::writableLocation(QStandardPaths::AppConfigLocation) + QStringLiteral("/autocorrect.txt");
    for (const QString &path : {QStringLiteral(":/autocorrect.txt"), own}) {
        QFile f(path);
        if (!f.open(QIODevice::ReadOnly | QIODevice::Text))
            continue;
        QTextStream in(&f);
        while (!in.atEnd()) {
            const QString line = in.readLine().trimmed();
            if (line.isEmpty() || line.startsWith(QLatin1Char('#')))
                continue;
            const qsizetype eq = line.indexOf(QLatin1Char('='));
            if (eq <= 0)
                continue;
            const QString typo = line.left(eq).trimmed().toLower();
            const QString fix = line.mid(eq + 1).trimmed();
            if (!typo.isEmpty() && !fix.isEmpty())
                m_corrections.insert(typo, fix);   // your own file comes last: it wins
        }
    }
}
