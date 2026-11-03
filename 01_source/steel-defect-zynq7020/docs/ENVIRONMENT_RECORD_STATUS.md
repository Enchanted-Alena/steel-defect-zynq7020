# 环境与历史训练记录状态：R3.1修订候选

本文件依据C交付编号02和A的接收说明修订，替代原R3内遗留的R2概括。它不是原训练机器的自动环境导出。

## 已有记录与证据等级

| 资料 | 已找到的内容 | 不能据此扩大的结论 |
|---|---|---|
| 历史项目组件说明 | Python3.12.7、NumPy1.26.4、Pillow10.4.0 | 不是原机器pip freeze/conda export，不能断言完整运行环境逐项精确一致 |
| 历史README训练命令 | python scripts/train_quantize_eval.py --epochs 45 | 是文档中的命令，不是带stdout和退出码的原训练终端日志；历史命令相对旧neu_cls目录 |
| model_contract_v1.json训练元数据 | epochs45、batch64、lr0.002、seed20261019、Adam、纯NumPy | 是与权重哈希关联的记录，不等于重训复现同一权重或完整历史决策审计 |
| 当前脚本默认值 | epochs30、batch64、lr0.002、seed20261019 | 默认值不是实际历史命令；45epochs由历史命令及合同另行记录 |
| B原R3实际验证环境 | Python3.12.14、NumPy2.3.5、Pillow12.3.0、pyserial3.5，带wheel哈希锁 | 本机验证环境，不回填为历史训练环境 |
| C编号02独立软件复核 | C记录Python3.12.7、NumPy1.26.4、Pillow10.4.0，合成3条生成和独立标量核对通过 | 这属于C本次复核，不是恢复了原训练机器，也不是ARM编译或板测 |

模型合同、收到的model_v1.npz及正式输入manifest之间存在SHA-256关联；公开源码不包含这些私有原件。关联证明身份，不代替原训练运行日志。

## 仍缺失的原始执行证据

尚未找到原训练机器运行时生成的完整pip/conda环境导出、依赖锁及带标准输出/退出码的原训练终端日志，亦无覆盖全部历史试验和人工选型的完整决策记录。
因此既不能写“环境、命令和参数完全没有记录”，也不能声称已精确恢复原机器或从头训练复现同一权重。
不通过重训补造历史记录；后续新运行须另行记为新轮次。

## 当前源码与验证状态

完整脚本集要求Python3.12；部分较简单脚本使用Path.is_relative_to只说明该API需要Python3.9以上，不能代表全仓库最低版本。
neu_cls/scripts/export_for_b_chain.py包含需要Python3.12语法的f-string，不能把Python3.11或更早环境写成全仓库已支持。
NumPy功能需求至少覆盖sliding_window_view（1.20起）；实际本机验证按requirements-validation-win-py312.lock执行，不外推所有版本组合均通过。

B原R3已实际安装依赖并运行载荷生成、标量核对、主机C算法和ARM编译；另有既有HLS RTL条件下的PS规范化和BD校验。
之后2026-11-02原模型前三条在既有兼容硬件上完成9条三路径正确性补测，不是正式270或性能复测。
C编号02已经完成首次独立复核，结论HOLD_FOR_DOCUMENT_FIXES；本修订候选仍需C差分复核。Skill为另交的外部附件，不能把原源码内未含Skill写成外部Skill不存在或已经通过复核。
详见VALIDATION_STATUS_R3.md/.json；不同来源、不同轮次和本修订的验证范围分开记录。
