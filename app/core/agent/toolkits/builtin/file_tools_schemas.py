"""File tool schema definitions -- recovered from bytecode."""

from __future__ import annotations

from typing import Any, Callable, Dict, List


def build_file_tool_schemas(
    find_file: Callable,
    read_file_snippet: Callable,
    read_full_document: Callable,
    list_recent_files: Callable,
    organize_file: Callable,
    rename_file: Callable,
    move_file: Callable,
    copy_file: Callable,
    delete_file: Callable,
    list_directory: Callable,
    directory_tree: Callable,
    get_disk_usage: Callable,
    find_large_files: Callable,
    find_old_files: Callable,
    batch_rename: Callable,
    batch_move: Callable,
    cleanup_duplicates: Callable,
    compress_files: Callable,
    extract_archive: Callable,
    manage_tag: Callable,
    manage_favorite: Callable,
    undo_last_op: Callable,
) -> List[Dict[str, Any]]:
    """Build file tool schema list with injected method references."""
    return [
        {
            "name": "find_file",
            "func": find_file,
            "description": "\u5728\u672c\u673a\u6216\u5de5\u4f5c\u533a\u4e2d\u641c\u7d22\u6587\u4ef6\uff0c\u652f\u6301\u6587\u4ef6\u540d\u548c\u5185\u5bb9\u5168\u6587\u641c\u7d22\u3002\u8fd4\u56de\u5339\u914d\u6587\u4ef6\u5217\u8868\uff08\u8def\u5f84\u3001\u7c7b\u522b\u3001\u5927\u5c0f\u3001\u6458\u8981\uff09\u3002",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "query": {
                        "type": "STRING",
                        "description": "\u641c\u7d22\u5173\u952e\u8bcd\uff0c\u652f\u6301\u4e2d\u82f1\u6587\u3001\u6587\u4ef6\u540d\u6216\u5185\u5bb9\u7247\u6bb5",
                    },
                    "category": {
                        "type": "STRING",
                        "description": "\u53ef\u9009\u3002\u6587\u4ef6\u7c7b\u522b\u8fc7\u6ee4\uff1a\u6587\u6863 / \u56fe\u7247 / \u89c6\u9891 / \u97f3\u9891 / \u4ee3\u7801 / \u538b\u7f29\u5305 / \u5176\u4ed6",
                    },
                    "limit": {
                        "type": "INTEGER",
                        "description": "\u6700\u591a\u8fd4\u56de\u6761\u6570\uff0c\u9ed8\u8ba4 10",
                    },
                },
                "required": ["query"],
            },
        },
        {
            "name": "read_file_snippet",
            "func": read_file_snippet,
            "description": "\u8bfb\u53d6\u4e00\u4e2a\u672c\u5730\u6587\u4ef6\u7684\u6587\u672c\u5185\u5bb9\uff08\u524d max_chars \u5b57\u7b26\uff09\u3002\u652f\u6301 txt / md / pdf / docx / xlsx / csv / json / py \u7b49\u683c\u5f0f\u3002",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {
                        "type": "STRING",
                        "description": "\u6587\u4ef6\u7684\u7edd\u5bf9\u8def\u5f84",
                    },
                    "max_chars": {
                        "type": "INTEGER",
                        "description": "\u6700\u591a\u8bfb\u53d6\u5b57\u7b26\u6570\uff0c\u9ed8\u8ba4 3000",
                    },
                },
                "required": ["path"],
            },
        },
        {
            "name": "read_full_document",
            "func": read_full_document,
            "description": "\u8bfb\u53d6\u672c\u5730\u6587\u4ef6\u7684\u5b8c\u6574\u5168\u6587\u5185\u5bb9\uff0c\u5c06\u6574\u4efd\u6587\u6863\u7eb3\u5165 LLM \u4e0a\u4e0b\u6587\u3002\u4e0e read_file_snippet \u7684\u533a\u522b\uff1a\u4e0d\u9650\u9875\u6570/\u884c\u6570\uff0cPDF \u8bfb\u53d6\u5168\u90e8\u9875\u9762\uff0cDOCX \u540c\u65f6\u63d0\u53d6\u6bb5\u843d\u4e0e\u8868\u683c\uff08\u8d22\u52a1\u8868\u683c\u5b8c\u6574\u4fdd\u7559\uff09\uff0cXLSX \u8bfb\u53d6\u6240\u6709 Sheet\u3002\u9002\u7528\u4e8e\u9700\u8981\u7cbe\u786e\u5f15\u7528\u539f\u6587\u6570\u636e\u7684\u5206\u6790\u573a\u666f\uff08\u8d22\u52a1\u62a5\u544a/\u5408\u540c/\u7814\u7a76\u62a5\u544a\uff09\u3002\u652f\u6301 pdf / docx / xlsx / csv / txt / md \u7b49\u683c\u5f0f\u3002",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {
                        "type": "STRING",
                        "description": "\u6587\u4ef6\u7684\u7edd\u5bf9\u8def\u5f84",
                    },
                    "max_chars": {
                        "type": "INTEGER",
                        "description": "\u6700\u591a\u8bfb\u53d6\u5b57\u7b26\u6570\uff0c\u9ed8\u8ba4 200000\uff08\u7ea6 15 \u4e07\u5b57\uff09\uff0c\u4e0a\u9650 200000",
                    },
                },
                "required": ["path"],
            },
        },
        {
            "name": "list_recent_files",
            "func": list_recent_files,
            "description": "\u5217\u51fa\u6700\u8fd1 N \u5929\u5185 Koto \u6536\u5f55\u7684\u6587\u4ef6\uff0c\u53ef\u6309\u7c7b\u522b\u8fc7\u6ee4\u3002\u8fd4\u56de\u6587\u4ef6\u5217\u8868\uff08\u8def\u5f84\u3001\u7c7b\u522b\u3001\u7d22\u5f15\u65f6\u95f4\uff09\u3002",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "days": {
                        "type": "INTEGER",
                        "description": "\u65f6\u95f4\u8303\u56f4\uff08\u5929\uff09\uff0c\u9ed8\u8ba4 7",
                    },
                    "category": {
                        "type": "STRING",
                        "description": "\u53ef\u9009\u7c7b\u522b\u8fc7\u6ee4",
                    },
                    "limit": {
                        "type": "INTEGER",
                        "description": "\u6700\u591a\u8fd4\u56de\u6761\u6570\uff0c\u9ed8\u8ba4 20",
                    },
                },
                "required": [],
            },
        },
        {
            "name": "organize_file",
            "func": organize_file,
            "description": "\u5c06\u6307\u5b9a\u6587\u4ef6\u81ea\u52a8\u6574\u7406\u5230\u5408\u9002\u7684\u76ee\u5f55\u4e0b\uff0c\u5e76\u6ce8\u518c\u5230\u6587\u4ef6\u5e93\u3002\u5982\u679c\u6587\u4ef6\u5df2\u7ecf\u5728\u6b63\u786e\u4f4d\u7f6e\uff0c\u4e5f\u4f1a\u786e\u4fdd\u5176\u88ab\u6536\u5f55\u5230\u7d22\u5f15\u4e2d\u3002\u8fd4\u56de\u6574\u7406\u7ed3\u679c\uff08\u6700\u7ec8\u8def\u5f84\u3001\u64cd\u4f5c\u8bf4\u660e\uff09\u3002",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "source_path": {
                        "type": "STRING",
                        "description": "\u5f85\u6574\u7406\u6587\u4ef6\u7684\u7edd\u5bf9\u8def\u5f84",
                    },
                    "category_hint": {
                        "type": "STRING",
                        "description": "\u53ef\u9009\uff0c\u544a\u77e5 Koto \u8be5\u6587\u4ef6\u5c5e\u4e8e\u54ea\u4e2a\u5927\u7c7b\uff0c\u5e2e\u52a9\u81ea\u52a8\u5f52\u6863",
                    },
                },
                "required": ["source_path"],
            },
        },
        {
            "name": "rename_file",
            "func": rename_file,
            "description": "\u5c06\u6587\u4ef6\u91cd\u547d\u540d\uff08\u4ec5\u6539\u540d\uff0c\u4e0d\u6539\u4f4d\u7f6e\uff09\u3002\u4f1a\u81ea\u52a8\u66f4\u65b0 Koto \u6587\u4ef6\u5e93\u8bb0\u5f55\uff0c\u5e76\u5199\u5165\u64cd\u4f5c\u65e5\u5fd7\u4f9b\u64a4\u9500\u3002",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {
                        "type": "STRING",
                        "description": "\u6587\u4ef6\u7684\u7edd\u5bf9\u8def\u5f84",
                    },
                    "new_name": {
                        "type": "STRING",
                        "description": "\u65b0\u7684\u6587\u4ef6\u540d\uff08\u542b\u6269\u5c55\u540d\uff0c\u5982 \u62a5\u544a_v2.docx\uff09",
                    },
                },
                "required": ["path", "new_name"],
            },
        },
        {
            "name": "move_file",
            "func": move_file,
            "description": "\u5c06\u6587\u4ef6\u79fb\u52a8\u5230\u53e6\u4e00\u4e2a\u76ee\u5f55\u3002\u76ee\u6807\u76ee\u5f55\u4e0d\u5b58\u5728\u65f6\u81ea\u52a8\u521b\u5efa\u3002\u4f1a\u66f4\u65b0\u6587\u4ef6\u5e93\u8bb0\u5f55\u3002",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "source_path": {
                        "type": "STRING",
                        "description": "\u6e90\u6587\u4ef6\u7684\u7edd\u5bf9\u8def\u5f84",
                    },
                    "dest_dir": {
                        "type": "STRING",
                        "description": "\u76ee\u6807\u76ee\u5f55\u7684\u7edd\u5bf9\u8def\u5f84",
                    },
                    "new_name": {
                        "type": "STRING",
                        "description": "\u53ef\u9009\uff0c\u79fb\u52a8\u540e\u91cd\u547d\u540d\u6587\u4ef6",
                    },
                },
                "required": ["source_path", "dest_dir"],
            },
        },
        {
            "name": "copy_file",
            "func": copy_file,
            "description": "\u590d\u5236\u6587\u4ef6\u5230\u53e6\u4e00\u4e2a\u76ee\u5f55\uff0c\u5e76\u5c06\u526f\u672c\u6ce8\u518c\u5230 Koto \u6587\u4ef6\u5e93\u3002",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "source_path": {
                        "type": "STRING",
                        "description": "\u6e90\u6587\u4ef6\u7684\u7edd\u5bf9\u8def\u5f84",
                    },
                    "dest_dir": {
                        "type": "STRING",
                        "description": "\u76ee\u6807\u76ee\u5f55\u7684\u7edd\u5bf9\u8def\u5f84",
                    },
                    "new_name": {
                        "type": "STRING",
                        "description": "\u53ef\u9009\uff0c\u526f\u672c\u7684\u6587\u4ef6\u540d",
                    },
                },
                "required": ["source_path", "dest_dir"],
            },
        },
        {
            "name": "delete_file",
            "func": delete_file,
            "description": "\u5220\u9664\u6587\u4ef6\u3002\u9ed8\u8ba4\u4f7f\u7528\u7cfb\u7edf\u56de\u6536\u7ad9\uff08\u5b89\u5168\uff09\uff0c\u8bbe use_trash=false \u5219\u6c38\u4e45\u5220\u9664\u3002\u64cd\u4f5c\u8bb0\u5f55\u5199\u5165\u65e5\u5fd7\uff0c\u53ef\u7528 undo_last_op \u64a4\u9500\uff08\u4ec5\u56de\u6536\u7ad9\u6a21\u5f0f\u6709\u6548\uff09\u3002",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {
                        "type": "STRING",
                        "description": "\u8981\u5220\u9664\u7684\u6587\u4ef6\u7edd\u5bf9\u8def\u5f84",
                    },
                    "use_trash": {
                        "type": "BOOLEAN",
                        "description": "\u662f\u5426\u9001\u5165\u56de\u6536\u7ad9\uff0c\u9ed8\u8ba4 true",
                    },
                },
                "required": ["path"],
            },
        },
        {
            "name": "list_directory",
            "func": list_directory,
            "description": "\u5217\u51fa\u6307\u5b9a\u76ee\u5f55\u4e0b\u7684\u6587\u4ef6\u548c\u5b50\u76ee\u5f55\uff0c\u53ef\u6309\u7c7b\u578b\u6216\u540d\u79f0\u8fc7\u6ee4\u3001\u6392\u5e8f\u3002",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {
                        "type": "STRING",
                        "description": "\u76ee\u5f55\u7684\u7edd\u5bf9\u8def\u5f84",
                    },
                    "show_hidden": {
                        "type": "BOOLEAN",
                        "description": "\u662f\u5426\u663e\u793a\u9690\u85cf\u6587\u4ef6\uff0c\u9ed8\u8ba4 false",
                    },
                    "filter_ext": {
                        "type": "STRING",
                        "description": "\u53ef\u9009\uff0c\u4ec5\u663e\u793a\u8be5\u6269\u5c55\u540d\u7684\u6587\u4ef6\uff0c\u5982 .pdf",
                    },
                    "sort_by": {
                        "type": "STRING",
                        "description": "\u6392\u5e8f\u5b57\u6bb5\uff1aname\uff08\u9ed8\u8ba4\uff09/ size / mtime",
                    },
                },
                "required": ["path"],
            },
        },
        {
            "name": "directory_tree",
            "func": directory_tree,
            "description": "\u4ee5\u6811\u72b6\u7ed3\u6784\u5c55\u793a\u76ee\u5f55\u53ca\u5176\u5b50\u76ee\u5f55\uff08\u6587\u4ef6\u5939\u5c42\u7ea7\uff09\u3002",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {
                        "type": "STRING",
                        "description": "\u8981\u5c55\u793a\u7684\u6839\u76ee\u5f55\u8def\u5f84",
                    },
                    "max_depth": {
                        "type": "INTEGER",
                        "description": "\u6700\u5927\u5c55\u5f00\u5c42\u6570\uff0c\u9ed8\u8ba4 3",
                    },
                },
                "required": ["path"],
            },
        },
        {
            "name": "get_disk_usage",
            "func": get_disk_usage,
            "description": "\u5206\u6790\u6307\u5b9a\u76ee\u5f55\u7684\u78c1\u76d8\u5360\u7528\uff0c\u5217\u51fa\u5404\u5b50\u76ee\u5f55\u5927\u5c0f\u6392\u884c\uff08Top N\uff09\u3002",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {
                        "type": "STRING",
                        "description": "\u8981\u5206\u6790\u7684\u76ee\u5f55\u7edd\u5bf9\u8def\u5f84",
                    },
                    "top_n": {
                        "type": "INTEGER",
                        "description": "\u8fd4\u56de\u5360\u7528\u6700\u5927\u7684\u524d N \u4e2a\u5b50\u76ee\u5f55\uff0c\u9ed8\u8ba4 10",
                    },
                },
                "required": ["path"],
            },
        },
        {
            "name": "find_large_files",
            "func": find_large_files,
            "description": "\u5728\u6307\u5b9a\u76ee\u5f55\uff08\u6216 Koto \u6587\u4ef6\u5e93\uff09\u4e2d\u67e5\u627e\u5927\u6587\u4ef6\u3002",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {
                        "type": "STRING",
                        "description": "\u53ef\u9009\uff0c\u626b\u63cf\u7684\u76ee\u5f55\u8def\u5f84\uff1b\u7701\u7565\u5219\u67e5 Koto \u6587\u4ef6\u5e93",
                    },
                    "min_size_mb": {
                        "type": "NUMBER",
                        "description": "\u6700\u5c0f\u6587\u4ef6\u5927\u5c0f\uff08MB\uff09\uff0c\u9ed8\u8ba4 10",
                    },
                    "limit": {
                        "type": "INTEGER",
                        "description": "\u6700\u591a\u8fd4\u56de\u6761\u6570\uff0c\u9ed8\u8ba4 20",
                    },
                },
                "required": [],
            },
        },
        {
            "name": "find_old_files",
            "func": find_old_files,
            "description": "\u5728 Koto \u6587\u4ef6\u5e93\u4e2d\u67e5\u627e\u957f\u671f\u672a\u4fee\u6539\u7684\u65e7\u6587\u4ef6\uff0c\u8f85\u52a9\u6e05\u7406\u51b3\u7b56\u3002",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "days_old": {
                        "type": "INTEGER",
                        "description": "\u8d85\u8fc7\u591a\u5c11\u5929\u672a\u4fee\u6539\u89c6\u4e3a\u65e7\u6587\u4ef6\uff0c\u9ed8\u8ba4 180",
                    },
                    "limit": {
                        "type": "INTEGER",
                        "description": "\u6700\u591a\u8fd4\u56de\u6761\u6570\uff0c\u9ed8\u8ba4 20",
                    },
                },
                "required": [],
            },
        },
        {
            "name": "batch_rename",
            "func": batch_rename,
            "description": "\u6279\u91cf\u91cd\u547d\u540d\u76ee\u5f55\u5185\u7684\u6587\u4ef6\u3002\u652f\u6301\u6b63\u5219\u66ff\u6362\u6a21\u5f0f\uff0c\u6216\u6309\u5e8f\u53f7/\u65e5\u671f\u524d\u7f00\u89c4\u5219\u7edf\u4e00\u6539\u540d\u3002",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "directory": {
                        "type": "STRING",
                        "description": "\u76ee\u6807\u76ee\u5f55\u7edd\u5bf9\u8def\u5f84",
                    },
                    "pattern": {
                        "type": "STRING",
                        "description": "\u6b63\u5219\u5339\u914d\u6a21\u5f0f\uff08\u4f5c\u7528\u4e8e\u6587\u4ef6\u540d\uff09",
                    },
                    "replacement": {
                        "type": "STRING",
                        "description": "\u66ff\u6362\u540e\u7684\u6587\u4ef6\u540d\u6a21\u677f\uff0c\u652f\u6301 \\1 \u7b49\u53cd\u5411\u5f15\u7528",
                    },
                    "file_filter": {
                        "type": "STRING",
                        "description": "\u53ef\u9009\uff0c\u53ea\u5904\u7406\u8be5\u6269\u5c55\u540d\u7684\u6587\u4ef6\uff0c\u5982 .jpg",
                    },
                    "dry_run": {
                        "type": "BOOLEAN",
                        "description": "\u662f\u5426\u9884\u6f14\uff08true = \u53ea\u663e\u793a\u53d8\u66f4\u4e0d\u6267\u884c\uff09\uff0c\u9ed8\u8ba4 true",
                    },
                },
                "required": ["directory", "pattern", "replacement"],
            },
        },
        {
            "name": "batch_move",
            "func": batch_move,
            "description": "\u6279\u91cf\u5c06\u4e00\u4e2a\u76ee\u5f55\u4e0b\u7b26\u5408\u6761\u4ef6\u7684\u6587\u4ef6\uff08\u6309\u7c7b\u522b\u6216\u6269\u5c55\u540d\uff09\u79fb\u52a8\u5230\u76ee\u6807\u76ee\u5f55\u3002",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "source_dir": {
                        "type": "STRING",
                        "description": "\u6765\u6e90\u76ee\u5f55",
                    },
                    "dest_dir": {
                        "type": "STRING",
                        "description": "\u76ee\u6807\u76ee\u5f55",
                    },
                    "category": {
                        "type": "STRING",
                        "description": "\u53ef\u9009\uff0c\u6587\u4ef6\u7c7b\u522b\u8fc7\u6ee4\uff08\u6587\u6863/\u56fe\u7247/\u89c6\u9891/\u97f3\u9891/\u4ee3\u7801/\u538b\u7f29\u5305\uff09",
                    },
                    "file_filter": {
                        "type": "STRING",
                        "description": "\u53ef\u9009\uff0c\u6269\u5c55\u540d\u8fc7\u6ee4\uff0c\u5982 .pdf",
                    },
                    "dry_run": {
                        "type": "BOOLEAN",
                        "description": "\u9884\u6f14\u6a21\u5f0f\uff0c\u9ed8\u8ba4 true",
                    },
                },
                "required": ["source_dir", "dest_dir"],
            },
        },
        {
            "name": "cleanup_duplicates",
            "func": cleanup_duplicates,
            "description": "\u6e05\u7406 Koto \u6587\u4ef6\u5e93\u4e2d\u5185\u5bb9\u76f8\u540c\uff08MD5 \u76f8\u540c\uff09\u7684\u91cd\u590d\u6587\u4ef6\uff0c\u6bcf\u7ec4\u4fdd\u7559\u4e00\u4e2a\u526f\u672c\uff0c\u5176\u4f59\u9001\u5165\u56de\u6536\u7ad9\u3002",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "keep_strategy": {
                        "type": "STRING",
                        "description": "\u4fdd\u7559\u7b56\u7565\uff1anewest\uff08\u9ed8\u8ba4\uff0c\u4fdd\u7559\u6700\u65b0\u4fee\u6539\uff09/ oldest / shortest_path",
                    },
                    "dry_run": {
                        "type": "BOOLEAN",
                        "description": "\u9884\u6f14\u6a21\u5f0f\uff0c\u9ed8\u8ba4 true",
                    },
                },
                "required": [],
            },
        },
        {
            "name": "compress_files",
            "func": compress_files,
            "description": "\u5c06\u591a\u4e2a\u6587\u4ef6\u6216\u6574\u4e2a\u76ee\u5f55\u6253\u5305\u6210 zip \u538b\u7f29\u6863\u3002",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "sources": {
                        "type": "ARRAY",
                        "description": "\u8981\u538b\u7f29\u7684\u6587\u4ef6\u6216\u76ee\u5f55\u8def\u5f84\u5217\u8868",
                        "items": {"type": "STRING"},
                    },
                    "output_path": {
                        "type": "STRING",
                        "description": "\u8f93\u51fa zip \u6587\u4ef6\u7684\u7edd\u5bf9\u8def\u5f84\uff08\u542b\u6587\u4ef6\u540d\uff09",
                    },
                },
                "required": ["sources", "output_path"],
            },
        },
        {
            "name": "extract_archive",
            "func": extract_archive,
            "description": "\u89e3\u538b zip / tar / tar.gz / tar.bz2 \u6863\u6848\u5230\u76ee\u6807\u76ee\u5f55\uff0c\u5e76\u6ce8\u518c\u91ca\u653e\u7684\u6587\u4ef6\u5230 Koto \u6587\u4ef6\u5e93\u3002",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "archive_path": {
                        "type": "STRING",
                        "description": "\u538b\u7f29\u6863\u7edd\u5bf9\u8def\u5f84",
                    },
                    "dest_dir": {
                        "type": "STRING",
                        "description": "\u89e3\u538b\u76ee\u6807\u76ee\u5f55\uff08\u7701\u7565\u5219\u89e3\u538b\u5230\u6863\u6848\u6240\u5728\u76ee\u5f55\uff09",
                    },
                },
                "required": ["archive_path"],
            },
        },
        {
            "name": "manage_tag",
            "func": manage_tag,
            "description": "\u7ba1\u7406\u6587\u4ef6\u6807\u7b7e\uff1a\u6dfb\u52a0\u3001\u79fb\u9664\u3001\u6e05\u9664\u6216\u5217\u51fa\u6807\u7b7e\u3002action \u53d6\u503c\uff1aadd / remove / list / clear / list_all\uff08\u67e5\u770b\u6240\u6709\u6807\u7b7e\u7edf\u8ba1\uff09\u3002",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "action": {
                        "type": "STRING",
                        "description": "\u64cd\u4f5c\uff1aadd / remove / list / clear / list_all / files_by_tag",
                    },
                    "path": {
                        "type": "STRING",
                        "description": "\u6587\u4ef6\u8def\u5f84\uff08list_all / files_by_tag \u65f6\u53ef\u7701\u7565\uff09",
                    },
                    "tag": {
                        "type": "STRING",
                        "description": "\u6807\u7b7e\u540d\u79f0\uff08action=files_by_tag \u65f6\u4f5c\u4e3a\u67e5\u8be2\u6761\u4ef6\uff09",
                    },
                },
                "required": ["action"],
            },
        },
        {
            "name": "manage_favorite",
            "func": manage_favorite,
            "description": "\u7ba1\u7406\u6536\u85cf\u5939\uff1a\u6dfb\u52a0\u6587\u4ef6\u3001\u79fb\u9664\u6587\u4ef6\u3001\u5217\u51fa\u5168\u90e8\u6536\u85cf\u3002action \u53d6\u503c\uff1aadd / remove / list\u3002",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "action": {
                        "type": "STRING",
                        "description": "\u64cd\u4f5c\uff1aadd / remove / list",
                    },
                    "path": {
                        "type": "STRING",
                        "description": "\u6587\u4ef6\u8def\u5f84\uff08list \u65f6\u53ef\u7701\u7565\uff09",
                    },
                },
                "required": ["action"],
            },
        },
        {
            "name": "undo_last_op",
            "func": undo_last_op,
            "description": "\u64a4\u9500\u4e0a\u4e00\u6b21\u6587\u4ef6\u64cd\u4f5c\uff08rename / move / copy / delete-to-trash\uff09\u3002",
            "parameters": {
                "type": "OBJECT",
                "properties": {},
                "required": [],
            },
        },
    ]
