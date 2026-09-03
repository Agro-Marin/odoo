"""Canvas geometry shared by the two models that persist it.

Not a model. These bounds cannot live on `ir.actions.server` or on
`automation.canvas.viewport`, because `ir_actions_server` already imports from
`automation_rule` and either owner would close an import cycle.
"""

NODE_SIZE_DEFAULT = {"width": 200, "height": 140}
NODE_SIZE_MIN = {"width": 160, "height": 72}
NODE_SIZE_MAX = {"width": 480, "height": 320}

NODE_HEADER_HEIGHT = 34

SCALE_MIN = 0.2
SCALE_MAX = 2.0
