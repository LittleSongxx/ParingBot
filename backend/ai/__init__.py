"""AI 能力层。

本项目所有与大模型、Agent 编排相关的代码都放在这个包里，
不允许散落到 api/ 或 service/ 中，目的是让 AI 链路能被单独阅读和替换。

    model_factory.py   从 ai_model_config 表读配置，构建对话模型
    prompt_loader.py   从 prompt_template 表读提示词，做三项校验并填变量
    tools.py           工具实现与 tool_code 到实现函数的分发表
    agents.py          子 Agent 的通用执行器：ReAct 循环、三道闸、写步骤记录
    graph.py           主管调度图的状态定义、节点与条件边
"""
