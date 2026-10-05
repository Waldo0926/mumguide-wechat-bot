import asyncio
import logging

from wxbot.alerts import AlertHandler


def test_alerts_are_plain_and_rate_limited():
    sent = []

    async def go():
        async def send(text):
            sent.append(text)
        handler = AlertHandler(send, asyncio.get_running_loop())
        log = logging.getLogger("wxbot.test")
        log.addHandler(handler)
        log.propagate = False
        try:
            log.warning("hub /ask failed: connection refused")
            log.warning("hub /ask failed: timeout")                  # same kind: suppressed
            log.warning("mp: reply to abc took over 4.0s")
            logging.getLogger("wxbot.alerts").warning("could not deliver alert")   # never loops
            logging.getLogger("aiohttp.access").warning("not ours")
            await asyncio.sleep(0.01)
        finally:
            log.removeHandler(handler)
    asyncio.run(go())
    assert len(sent) == 2
    assert "连不上 Monash Hub" in sent[0] and "超过 4 秒" in sent[1]
