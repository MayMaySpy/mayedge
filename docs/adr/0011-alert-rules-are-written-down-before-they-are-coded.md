# Alert rules are written down before they are coded

Every alert the desk can raise is a numbered rule in [alert-rules.md](../alert-rules.md): what trips it, what it is called, how it is scored, and what the record says. A rule changes there first. The knob, the code and the test that pins it follow in the same commit.

The rules used to live in three places: thresholds in `alerts.yaml`, a label cascade in code, and a few words in the glossary. Nobody could say what "Short squeeze" promised, so nothing could be called noise. A rule that cannot say what it expects is listed as open, and stays a candidate to go.
