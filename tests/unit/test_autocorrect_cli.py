"""CLI input modes for local autocorrect."""
import io

from distrokit import cli



def test_autocorrect_accepts_text_arguments(monkeypatch):
    monkeypatch.setattr(cli.sys, 'stdin', io.StringIO(''))
    monkeypatch.setattr(cli.sys, 'stdout', io.StringIO())
    from distrokit import autocorrect
    monkeypatch.setattr(autocorrect, 'correct_text', lambda text: 'FIXED:' + text)
    args = cli.build_parser().parse_args(['autocorrect', 'fix', 'this', 'text'])
    assert args.func(args) == 0
    assert cli.sys.stdout.getvalue() == 'FIXED:fix this text\n'


def test_autocorrect_reads_piped_stdin(monkeypatch):
    monkeypatch.setattr(cli.sys, 'stdin', io.StringIO('piped words'))
    monkeypatch.setattr(cli.sys, 'stdout', io.StringIO())
    from distrokit import autocorrect
    monkeypatch.setattr(autocorrect, 'correct_text', lambda text: text.upper())
    args = cli.build_parser().parse_args(['autocorrect'])
    assert args.func(args) == 0
    assert cli.sys.stdout.getvalue() == 'PIPED WORDS\n'


def test_autocorrect_prompts_when_interactive(monkeypatch):
    class TTY(io.StringIO):
        def isatty(self): return True
    monkeypatch.setattr(cli.sys, 'stdin', TTY())
    monkeypatch.setattr(cli.sys, 'stdout', io.StringIO())
    monkeypatch.setattr('builtins.input', lambda: 'typed text')
    from distrokit import autocorrect
    monkeypatch.setattr(autocorrect, 'correct_text', lambda text: 'corrected')
    args = cli.build_parser().parse_args(['autocorrect'])
    assert args.func(args) == 0
    assert cli.sys.stdout.getvalue() == 'corrected\n'


def test_autocorrect_selection_is_explicit(monkeypatch):
    from distrokit import autocorrect
    monkeypatch.setattr(autocorrect, 'correct_selection', lambda: 7)
    args = cli.build_parser().parse_args(['autocorrect', '--selection'])
    assert args.func(args) == 7
