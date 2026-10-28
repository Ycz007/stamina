# SPDX-License-Identifier: MIT

import pytest

import stamina


@pytest.fixture(params=[False, True], ids=["hook", "prometheus"])
def retry_details(request, monkeypatch):
    """
    Capture retry details and optionally check the real Prometheus hook.
    """
    details = []
    hooks = [details.append]
    counter = None
    if request.param:
        prometheus = pytest.importorskip("prometheus_client")
        from stamina.instrumentation import _prometheus

        counter = prometheus.Counter(
            "stamina_retries_total",
            "Total number of retries.",
            ("callable", "retry_num", "error_type"),
            registry=None,
        )
        monkeypatch.setattr(_prometheus, "RETRIES_TOTAL", counter)
        hooks.append(_prometheus.init_prometheus())

    stamina.instrumentation.set_on_retry_hooks(hooks)

    yield details

    if counter is not None:
        samples = [
            sample
            for metric in counter.collect()
            for sample in metric.samples
            if sample.name == "stamina_retries_total"
        ]

        assert 1 == len(samples)
        assert details[0].name == samples[0].labels["callable"]
        assert 1 == samples[0].value


@pytest.mark.parametrize("name", [None, "fetch-catalog", ""])
@pytest.mark.parametrize("kind", ["context", "caller", "bound"])
def test_operation_name(name, kind, retry_details):
    """
    Explicit names reach retry hooks without changing unnamed operations.
    """
    details = retry_details
    options = {"attempts": 2, "wait_max": 0}
    if name is not None:
        options["name"] = name

    def fail():
        raise ValueError

    def run():
        if kind == "context":
            for attempt in stamina.retry_context(ValueError, **options):
                with attempt:
                    fail()
        else:
            caller = stamina.RetryingCaller(**options)
            if kind == "bound":
                caller.on(ValueError)(fail)
            else:
                caller(ValueError, fail)

    with pytest.raises(ValueError):
        run()

    assert 1 == len(details)
    assert ("<context block>" if name is None else name) == details[0].name


@pytest.mark.anyio
@pytest.mark.parametrize("name", [None, "fetch-catalog", ""])
@pytest.mark.parametrize("kind", ["context", "caller", "bound"])
async def test_async_operation_name(name, kind, retry_details):
    """
    Async contexts and both caller forms preserve explicit operation names.
    """
    details = retry_details
    options = {"attempts": 2, "wait_max": 0}
    if name is not None:
        options["name"] = name

    async def fail():
        raise ValueError

    async def run():
        if kind == "context":
            async for attempt in stamina.retry_context(ValueError, **options):
                with attempt:
                    await fail()
        else:
            caller = stamina.AsyncRetryingCaller(**options)
            if kind == "bound":
                await caller.on(ValueError)(fail)
            else:
                await caller(ValueError, fail)

    with pytest.raises(ValueError):
        await run()

    assert 1 == len(details)
    assert ("<context block>" if name is None else name) == details[0].name


@pytest.mark.parametrize(
    "caller_type", [stamina.RetryingCaller, stamina.AsyncRetryingCaller]
)
@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("name", ["fetch-catalog", "", "<context block>"])
def test_named_caller_repr(caller_type, bound, name):
    """
    Caller representations identify explicitly named operations.
    """
    caller = caller_type(name=name)
    if bound:
        caller = caller.on(ValueError)

    if name == "<context block>":
        assert "name=" not in repr(caller)
    else:
        assert f"name={name!r}" in repr(caller)
