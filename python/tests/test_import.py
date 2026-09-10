"""Import smoke test: the package and its public surface must import cleanly."""

import browser_agent


def test_public_surface() -> None:
    assert browser_agent.__version__ == "0.1.0"
    assert browser_agent.BrowserSession is not None
    assert browser_agent.SemanticSnapshot is not None
    assert browser_agent.TaskState is not None
    assert browser_agent.WorkingMemory is not None
