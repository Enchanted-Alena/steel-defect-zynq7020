# 板端验收与工件边界

已接受Protocol2测试使用固定test270（每类45），三路径预测和logits一致，正确217/270。
正式270样本ELF采用轮询；独立ISR smoke ELF证明ISR 5/5。二者共享批准bit/XSA，分别锁定ELF。
本源码RC不包含这些二进制、私有模型/输入/Golden或逐样本UART日志，也不声称本轮重新板测。
所引用聚合结果见reports/MARGIN930_RESULTS.md，输入边界见reports/preprocessing_contract.md。
