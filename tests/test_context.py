import asyncio

import pytest

from breba_app.context import BrebaContext, bind_context, get_context, init_context


def test_default_context_is_empty():
    ctx = get_context()
    assert isinstance(ctx, BrebaContext)
    assert ctx.request_id is None
    assert ctx.user_id is None
    assert ctx.product_id is None


def test_init_context_auto_generates_request_id():
    init_context(user_id="u1", product_id="p1")
    ctx = get_context()
    assert ctx.user_id == "u1"
    assert ctx.product_id == "p1"
    assert ctx.request_id is not None
    assert len(ctx.request_id) == 32  # uuid4 hex


def test_init_context_honors_explicit_request_id():
    init_context(request_id="explicit", user_id="u1")
    assert get_context().request_id == "explicit"


def test_init_context_replaces_prior_context():
    init_context(request_id="r1", user_id="u1", product_id="p1")
    init_context(user_id="u2")
    ctx = get_context()
    assert ctx.user_id == "u2"
    assert ctx.product_id is None  # not carried over
    assert ctx.request_id is not None and ctx.request_id != "r1"


def test_bind_context_restores_previous():
    init_context(request_id="outer", user_id="u1")
    with bind_context(request_id="inner", user_id="u2"):
        assert get_context().request_id == "inner"
        assert get_context().user_id == "u2"
    assert get_context().request_id == "outer"
    assert get_context().user_id == "u1"


def test_bind_context_restores_on_exception():
    init_context(request_id="outer")
    with pytest.raises(RuntimeError):
        with bind_context(request_id="inner"):
            raise RuntimeError("boom")
    assert get_context().request_id == "outer"


def test_breba_context_is_frozen():
    ctx = BrebaContext(request_id="r1")
    with pytest.raises(Exception):  # FrozenInstanceError
        ctx.request_id = "r2"  # type: ignore[misc]


@pytest.mark.asyncio
async def test_concurrent_tasks_do_not_collide():
    """Each asyncio task must see its own BrebaContext — simulates concurrent requests."""
    seen: dict[str, BrebaContext] = {}
    barrier = asyncio.Event()

    async def worker(name: str, user_id: str, product_id: str):
        init_context(user_id=user_id, product_id=product_id)
        # Let all workers init before any of them reads, to force interleaving
        await asyncio.sleep(0.01)
        await barrier.wait()
        # Each task should still see its own context after the await suspension
        seen[name] = get_context()

    async def releaser():
        await asyncio.sleep(0.05)
        barrier.set()

    await asyncio.gather(
        worker("a", "user_a", "prod_a"),
        worker("b", "user_b", "prod_b"),
        worker("c", "user_c", "prod_c"),
        releaser(),
    )

    assert seen["a"].user_id == "user_a" and seen["a"].product_id == "prod_a"
    assert seen["b"].user_id == "user_b" and seen["b"].product_id == "prod_b"
    assert seen["c"].user_id == "user_c" and seen["c"].product_id == "prod_c"
    # request_ids must be distinct
    assert len({seen["a"].request_id, seen["b"].request_id, seen["c"].request_id}) == 3


@pytest.mark.asyncio
async def test_child_task_inherits_but_does_not_leak():
    """A child task started inside a context inherits it; mutations in the child must not leak to the parent."""
    init_context(request_id="parent", user_id="parent_user")

    async def child():
        # Child inherits parent's context at task creation
        assert get_context().user_id == "parent_user"
        # Child reassigns — must not affect parent
        init_context(user_id="child_user")
        assert get_context().user_id == "child_user"

    await asyncio.create_task(child())

    # Parent context untouched
    assert get_context().user_id == "parent_user"
    assert get_context().request_id == "parent"


@pytest.mark.asyncio
async def test_bind_context_isolates_across_concurrent_tasks():
    """Two tasks each using bind_context concurrently must not see each other's bound values."""
    results: dict[str, str | None] = {}

    async def worker(name: str, rid: str):
        with bind_context(request_id=rid, user_id=f"u_{name}"):
            await asyncio.sleep(0.02)  # yield to the other task mid-block
            results[name] = get_context().user_id

    await asyncio.gather(worker("x", "r_x"), worker("y", "r_y"))

    assert results["x"] == "u_x"
    assert results["y"] == "u_y"
