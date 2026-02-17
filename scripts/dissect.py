#!/usr/bin/env python3
"""
dead-drop dissect — Extract code structure from a project using tree-sitter.

Outputs a CODE_MAP.md with function/struct/class outlines per file,
so agents can navigate without reading entire files.

Usage:
    python3 dissect.py [project_root] [--output .dead-drop/CODE_MAP.md]
    python3 dissect.py /path/to/project --extensions .cpp,.h,.c,.m,.metal,.py
"""

import argparse
import os
import sys
from pathlib import Path

# Language detection by extension
EXT_TO_LANG = {
    '.c': 'c',
    '.h': 'c',       # default C for .h, override with context
    '.m': 'c',       # Objective-C parsed as C for structure
    '.cpp': 'cpp',
    '.cc': 'cpp',
    '.cxx': 'cpp',
    '.hpp': 'cpp',
    '.hh': 'cpp',
    '.metal': 'cpp',  # Metal shaders close enough to C++
    '.py': 'python',
    '.js': 'javascript',
    '.ts': 'javascript',  # close enough for structure
}

# tree-sitter node types that represent "interesting" structure
STRUCTURE_NODES = {
    'c': [
        'function_definition',
        'struct_specifier',
        'enum_specifier',
        'type_definition',
        'preproc_function_def',
    ],
    'cpp': [
        'function_definition',
        'class_specifier',
        'struct_specifier',
        'enum_specifier',
        'type_definition',
        'namespace_definition',
        'template_declaration',
        'preproc_function_def',
    ],
    'python': [
        'function_definition',
        'class_definition',
    ],
    'javascript': [
        'function_declaration',
        'class_declaration',
        'method_definition',
        'arrow_function',
        'export_statement',
    ],
}

# Directories to skip
SKIP_DIRS = {
    'node_modules', '.git', 'build', 'cmake-build-debug', 'cmake-build-release',
    '__pycache__', '.venv', 'venv', 'vendor', 'third_party', 'external',
    'kompute',  # ggml vendored lib
    'ggml-cann', 'ggml-sycl', 'ggml-vulkan', 'ggml-cuda', 'ggml-amx',
    'ggml-kompute', 'ggml-rpc',  # backends we don't use
}


def get_parser(lang):
    """Get tree-sitter parser for a language."""
    import tree_sitter
    if lang == 'c':
        import tree_sitter_c
        return tree_sitter.Language(tree_sitter_c.language()), lang
    elif lang == 'cpp':
        import tree_sitter_cpp
        return tree_sitter.Language(tree_sitter_cpp.language()), lang
    elif lang == 'python':
        import tree_sitter_python
        return tree_sitter.Language(tree_sitter_python.language()), lang
    elif lang == 'javascript':
        import tree_sitter_javascript
        return tree_sitter.Language(tree_sitter_javascript.language()), lang
    return None, None


def extract_name(node, source_bytes):
    """Extract the name/identifier from a structure node."""
    # For function definitions, look for declarator
    if node.type in ('function_definition',):
        decl = node.child_by_field_name('declarator')
        if decl:
            # Could be pointer_declarator wrapping function_declarator
            while decl.type in ('pointer_declarator', 'reference_declarator'):
                decl = decl.children[-1] if decl.children else decl
            if decl.type == 'function_declarator':
                name_node = decl.child_by_field_name('declarator')
                if name_node:
                    # Handle qualified names like ClassName::method
                    return source_bytes[name_node.start_byte:name_node.end_byte].decode('utf-8', errors='replace')
            return source_bytes[decl.start_byte:decl.end_byte].decode('utf-8', errors='replace').split('(')[0].strip()

    # For class/struct/enum
    if node.type in ('class_specifier', 'struct_specifier', 'enum_specifier', 'class_definition'):
        name_node = node.child_by_field_name('name')
        if name_node:
            return source_bytes[name_node.start_byte:name_node.end_byte].decode('utf-8', errors='replace')

    # For namespace
    if node.type == 'namespace_definition':
        name_node = node.child_by_field_name('name')
        if name_node:
            return source_bytes[name_node.start_byte:name_node.end_byte].decode('utf-8', errors='replace')

    # For typedef
    if node.type == 'type_definition':
        # Last identifier child is typically the typedef name
        for child in reversed(node.children):
            if child.type == 'type_identifier':
                return source_bytes[child.start_byte:child.end_byte].decode('utf-8', errors='replace')

    # Python function/class
    if node.type in ('function_definition', 'class_definition'):
        name_node = node.child_by_field_name('name')
        if name_node:
            return source_bytes[name_node.start_byte:name_node.end_byte].decode('utf-8', errors='replace')

    # JS
    if node.type in ('function_declaration', 'class_declaration'):
        name_node = node.child_by_field_name('name')
        if name_node:
            return source_bytes[name_node.start_byte:name_node.end_byte].decode('utf-8', errors='replace')

    # Fallback: grab first line
    first_line = source_bytes[node.start_byte:node.end_byte].decode('utf-8', errors='replace').split('\n')[0][:80]
    return first_line


def node_type_label(node_type):
    """Human-readable label for node type."""
    labels = {
        'function_definition': 'fn',
        'function_declaration': 'fn',
        'class_specifier': 'class',
        'class_definition': 'class',
        'class_declaration': 'class',
        'struct_specifier': 'struct',
        'enum_specifier': 'enum',
        'type_definition': 'typedef',
        'namespace_definition': 'namespace',
        'template_declaration': 'template',
        'preproc_function_def': 'macro',
        'method_definition': 'method',
        'arrow_function': 'fn',
        'export_statement': 'export',
    }
    return labels.get(node_type, node_type)


def walk_tree(node, lang, source_bytes, depth=0, max_depth=50):
    """Walk AST and collect structure nodes."""
    if depth > max_depth:
        return []
    results = []
    target_types = STRUCTURE_NODES.get(lang, [])

    if node.type in target_types:
        name = extract_name(node, source_bytes)
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        line_count = end_line - start_line + 1
        results.append({
            'type': node_type_label(node.type),
            'name': name,
            'start': start_line,
            'end': end_line,
            'lines': line_count,
            'depth': depth,
        })
        # Don't recurse into nested functions for top-level view
        # But do recurse into namespaces/classes to find methods
        if node.type in ('namespace_definition', 'class_specifier', 'class_definition', 'struct_specifier'):
            for child in node.children:
                results.extend(walk_tree(child, lang, source_bytes, depth + 1, max_depth))
        return results

    for child in node.children:
        results.extend(walk_tree(child, lang, source_bytes, depth + 1, max_depth))

    return results


def dissect_file(filepath, parsers_cache):
    """Parse a single file and return its structure."""
    ext = Path(filepath).suffix.lower()
    lang = EXT_TO_LANG.get(ext)
    if not lang:
        return None

    # .h files: check if C++ features present
    if ext == '.h':
        try:
            with open(filepath, 'r', errors='replace') as f:
                content = f.read(4096)
                if 'class ' in content or 'namespace ' in content or 'template' in content:
                    lang = 'cpp'
        except:
            pass

    if lang not in parsers_cache:
        language, _ = get_parser(lang)
        if language is None:
            return None
        import tree_sitter
        parser = tree_sitter.Parser(language)
        parsers_cache[lang] = parser
    else:
        parser = parsers_cache[lang]

    try:
        with open(filepath, 'rb') as f:
            source = f.read()
    except:
        return None

    tree = parser.parse(source)
    symbols = walk_tree(tree.root_node, lang, source)

    total_lines = source.count(b'\n') + 1

    return {
        'path': filepath,
        'lang': lang,
        'total_lines': total_lines,
        'symbols': symbols,
    }


def find_source_files(root, extensions=None):
    """Find all source files, respecting skip dirs."""
    files = []
    if extensions:
        valid_exts = set(extensions)
    else:
        valid_exts = set(EXT_TO_LANG.keys())

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skip dirs
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for fname in sorted(filenames):
            if Path(fname).suffix.lower() in valid_exts:
                files.append(os.path.join(dirpath, fname))

    return files


def format_output(results, root):
    """Format results as markdown."""
    lines = []
    lines.append("# Code Map\n")
    lines.append(f"Auto-generated by `dissect.py`. Do not edit manually.\n")
    lines.append(f"Project: `{root}`\n")
    lines.append("---\n")

    # Group by directory
    from collections import defaultdict
    by_dir = defaultdict(list)
    for r in results:
        rel = os.path.relpath(r['path'], root)
        dirname = os.path.dirname(rel) or '.'
        by_dir[dirname].append((rel, r))

    for dirname in sorted(by_dir.keys()):
        lines.append(f"\n## {dirname}/\n")

        for rel_path, r in sorted(by_dir[dirname], key=lambda x: x[0]):
            fname = os.path.basename(rel_path)
            lines.append(f"\n### `{rel_path}` ({r['total_lines']}L, {r['lang']})\n")

            if not r['symbols']:
                lines.append("*(no top-level symbols extracted)*\n")
                continue

            lines.append("| Type | Name | Lines | Range |")
            lines.append("|------|------|-------|-------|")

            for sym in r['symbols']:
                indent = "  " * sym['depth']
                name = sym['name']
                # Truncate long names
                if len(name) > 60:
                    name = name[:57] + "..."
                lines.append(f"| {sym['type']} | {indent}`{name}` | {sym['lines']} | {sym['start']}-{sym['end']} |")

    # Summary
    total_files = len(results)
    total_lines = sum(r['total_lines'] for r in results)
    total_symbols = sum(len(r['symbols']) for r in results)
    lines.append(f"\n---\n")
    lines.append(f"**Total:** {total_files} files, {total_lines:,} lines, {total_symbols} symbols\n")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description='Dissect codebase structure with tree-sitter')
    parser.add_argument('root', nargs='?', default='.', help='Project root directory')
    parser.add_argument('--output', '-o', default=None, help='Output file (default: .dead-drop/CODE_MAP.md)')
    parser.add_argument('--extensions', '-e', default=None, help='Comma-separated extensions (e.g. .cpp,.h,.c)')
    parser.add_argument('--stdout', action='store_true', help='Print to stdout instead of file')
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"Error: {root} is not a directory", file=sys.stderr)
        sys.exit(1)

    extensions = None
    if args.extensions:
        extensions = [e.strip() if e.startswith('.') else f'.{e.strip()}' for e in args.extensions.split(',')]

    print(f"Scanning {root}...", file=sys.stderr)
    files = find_source_files(root, extensions)
    print(f"Found {len(files)} source files", file=sys.stderr)

    parsers_cache = {}
    results = []
    for f in files:
        r = dissect_file(f, parsers_cache)
        if r:
            results.append(r)

    print(f"Parsed {len(results)} files, extracted {sum(len(r['symbols']) for r in results)} symbols", file=sys.stderr)

    output = format_output(results, root)

    if args.stdout:
        print(output)
    else:
        out_path = args.output or os.path.join(root, '.dead-drop', 'CODE_MAP.md')
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, 'w') as f:
            f.write(output)
        print(f"Written to {out_path}", file=sys.stderr)


if __name__ == '__main__':
    main()
