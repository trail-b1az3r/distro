#pragma once
// Spelling for the editor: misspelled words underlined (Highlighter asks isMisspelled), suggestions and a personal
// dictionary through KDE's Sonnet (Hunspell or Aspell dictionaries), and autocorrect as you type.
//
// Autocorrect never guesses: it fixes only known typos (data/autocorrect.txt, and your own in
// ~/.config/<app>/autocorrect.txt, one "wrong=right" a line), two initial capitals ("THe" -> "The") and a lone "i".
// Both are on by default, and kept in the app's settings.
#include <QHash>
#include <QObject>
#include <QSet>
#include <QStringList>
#include <QtQml/qqmlregistration.h>

namespace Sonnet { class Speller; }
class QQmlEngine;
class QJSEngine;

class Spelling : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON
    Q_PROPERTY(bool enabled READ enabled WRITE setEnabled NOTIFY changed)
    Q_PROPERTY(bool autocorrect READ autocorrect WRITE setAutocorrect NOTIFY changed)
    Q_PROPERTY(bool available READ available NOTIFY changed)
    Q_PROPERTY(QString language READ language NOTIFY changed)

public:
    explicit Spelling(QObject *parent = nullptr);
    static Spelling *instance();
    static Spelling *create(QQmlEngine *, QJSEngine *);
    ~Spelling() override;

    bool enabled() const { return m_enabled; }
    void setEnabled(bool on);
    bool autocorrect() const { return m_autocorrect; }
    void setAutocorrect(bool on);
    // A dictionary is installed and loaded.
    bool available() const;
    QString language() const;

    // Whether a word is worth checking: letters (and apostrophes), not all capitals (acronyms), no digits.
    static bool checkable(const QString &word);
    Q_INVOKABLE bool isMisspelled(const QString &word) const;
    Q_INVOKABLE QStringList suggestions(const QString &word, int max = 6) const;
    // Into the personal dictionary (kept by Sonnet, for every app that uses it).
    Q_INVOKABLE void addToDictionary(const QString &word);
    // Not marked again until the app closes.
    Q_INVOKABLE void ignore(const QString &word);
    // What autocorrect makes of a word just typed: the fix, or an empty string to leave it.
    Q_INVOKABLE QString correction(const QString &word) const;

signals:
    void changed();

private:
    void loadCorrections();
    static QString matchCase(const QString &typed, const QString &fix);

    Sonnet::Speller *m_speller = nullptr;
    bool m_enabled = true;
    bool m_autocorrect = true;
    QSet<QString> m_ignored;
    QHash<QString, QString> m_corrections;   // lower-case typo -> fix
    static Spelling *s_instance;
};
