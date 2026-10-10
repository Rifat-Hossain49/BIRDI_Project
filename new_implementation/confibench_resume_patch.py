"""Instrument only copied baseline code, leaving the original repository intact."""
import ast


def patch_task_source(source, profile):
    tree = ast.parse(source)
    task = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'AutoLine_Task')
    init = next(n for n in task.body if isinstance(n, ast.FunctionDef) and n.name == '__init__')
    core = next(n for n in task.body if isinstance(n, ast.FunctionDef) and n.name == 'run_stages_core')
    loops = [n for n in ast.walk(core) if isinstance(n, ast.For)
             and ast.unparse(n.iter) == 'range(self.iter_max)']
    if len(loops) != 1:
        raise ValueError('Expected exactly one baseline iteration loop')
    loop = loops[0]
    loop.iter = ast.parse('range(self._resume_start if not self._resume_eval_ready else self.iter_max, self.iter_max)',
                          mode='eval').body

    class Boundaries(ast.NodeTransformer):
        def visit_Continue(self, node):
            return ast.parse('commit_iteration(self, i + 1, False)\ncontinue').body

        def visit_Break(self, node):
            return ast.parse('commit_iteration(self, i + 1, True)\nbreak').body

        def visit_For(self, node):
            return node  # Do not instrument unrelated nested loops.

    rewriter = Boundaries()
    rewritten = []
    for statement in loop.body:
        result = rewriter.visit(statement)
        rewritten.extend(result if isinstance(result, list) else [result])
    loop.body = rewritten
    loop.body[:0] = ast.parse('prepare_iteration_path(self, i)').body
    loop.body.extend(ast.parse('commit_iteration(self, i + 1, True if i + 1 == self.iter_max else False)').body)
    # Continue on the last iteration also reaches evaluation on restart.
    ast.fix_missing_locations(core)
    lines = source.splitlines(keepends=True)
    patched_core = '\n'.join('    ' + line for line in ast.unparse(core).splitlines()) + '\n'
    # Apply from the bottom so original line offsets remain valid.
    lines[core.lineno - 1:core.end_lineno] = [patched_core]
    lines[init.end_lineno:init.end_lineno] = [f'        begin_task(self, {profile!r})\n']
    patched = 'from confibench_resume import begin_task, commit_iteration, prepare_iteration_path\n' + ''.join(lines)
    compile(patched, '<resumable baseline>', 'exec')
    return patched
