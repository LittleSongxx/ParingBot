#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线评测库：种子数据、规则口径、指标与报告渲染。

四个模块互不依赖后端：

* lib.seed    解析种子 SQL → Member / Preference
* lib.rules   硬规则与档位口径（与 backend/service 对齐）
* lib.metrics 交付/一致性/NDCG/统计置信区间
* lib.render  把结果字典渲染成 Markdown

只依赖 Python 3.10 标准库。
"""

__version__ = "3.0.0"

__all__ = ["seed", "rules", "metrics", "render"]