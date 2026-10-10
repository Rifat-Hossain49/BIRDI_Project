"""Kill timed-out pure parser calls while preserving their outputs and exceptions."""
import multiprocessing
import time
from functools import wraps


def run_with_timeout(timeout):
    def decorate(func):
        @wraps(func)
        def call(*args, **kwargs):
            context = multiprocessing.get_context('fork')
            reader, writer = context.Pipe(duplex=False)

            def invoke():
                reader.close()
                try:
                    writer.send((True, func(*args, **kwargs)))
                except Exception as error:
                    writer.send((False, error))
                finally:
                    writer.close()

            process = context.Process(target=invoke)
            process.start()
            writer.close()
            try:
                if not reader.poll(timeout):
                    raise TimeoutError(f'Function call timed out after {timeout} seconds')
                try:
                    ok, value = reader.recv()
                except EOFError as error:
                    raise RuntimeError(f'Parser process exited without a result: {process.exitcode}') from error
                if not ok:
                    raise value
                return value
            finally:
                reader.close()
                if process.is_alive():
                    process.terminate()
                process.join(timeout=2)
                if process.is_alive():
                    process.kill()
                    process.join()
        return call
    return decorate


def self_test():
    before = {p.pid for p in multiprocessing.active_children()}
    assert run_with_timeout(2)(lambda: 'x' * 100000)() == 'x' * 100000
    try:
        run_with_timeout(2)(lambda: int('invalid'))()
    except ValueError:
        pass
    else:
        raise AssertionError('Parser exception lost')
    try:
        run_with_timeout(0.05)(lambda: time.sleep(60))()
    except TimeoutError:
        pass
    else:
        raise AssertionError('Parser timeout lost')
    assert {p.pid for p in multiprocessing.active_children()} == before
    print('PARSER_TIMEOUT_GUARD_SMOKE_OK', flush=True)
