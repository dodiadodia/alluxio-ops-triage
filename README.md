# Alluxio Ops Triage Skill

面向 Alluxio Enterprise AI Support 和运维人员的 Codex skill。它用于从在线环境、Diagnostic Snapshot、collectinfo、日志、指标、配置和源码中整理证据，形成可验证的故障假设、恢复建议和 Support 交接报告。

该 skill 默认只诊断、不执行生产变更。它不是自动修复工具，也不替代与实际版本匹配的 Alluxio 官方文档、变更流程或 Alluxio 专家判断。

## 适用场景

| 场景 | 能力 |
|---|---|
| Kubernetes 在线排障 | 识别部署拓扑，关联应用、FUSE/CSI、Worker、Coordinator、etcd、UFS 和节点证据 |
| Docker 或物理机排障 | 基于服务、进程、日志、磁盘和网络证据定位组件问题 |
| 离线诊断包分析 | 安全扫描 Diagnostic Snapshot、collectinfo 目录或 tar 包，提取版本、时间线和高风险信号 |
| etcd 故障 | 区分节点异常、quorum、`NOSPACE`、碎片化和疑似数据损坏，并提供受控恢复门禁 |
| 性能与容量问题 | 分析缓存、UFS、FUSE、任务调度、页存储和 etcd 指标，避免脱离基线下结论 |
| Support 升级 | 输出根因置信度、证据、数据缺口、变更风险、验证与回滚方案 |

不适用于与 Alluxio 无关的通用 Kubernetes 故障，也不用于普通代码审查或功能开发。

## 安装

将仓库放入 Codex skills 目录：

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
git clone git@github.com:dodiadodia/alluxio-ops-triage.git \
  "${CODEX_HOME:-$HOME/.codex}/skills/alluxio-ops-triage"
```

如果已经安装，更新到最新版本：

```bash
git -C "${CODEX_HOME:-$HOME/.codex}/skills/alluxio-ops-triage" pull --ff-only
```

安装或更新后，在新的 Codex 任务中显式调用 `$alluxio-ops-triage`，或描述一个与 Alluxio 运维排障明确相关的问题。

## 使用示例

```text
使用 $alluxio-ops-triage 分析这个 Diagnostic Snapshot，只做离线诊断，不执行任何集群变更。
```

```text
使用 $alluxio-ops-triage 排查 Alluxio FUSE 出现 Transport endpoint is not connected。
先给出证据收集命令和假设表，不要重启 Pod。
```

```text
使用 $alluxio-ops-triage 分析 etcd NOSPACE 告警，输出恢复前置条件、风险、停止条件、验证和回滚方案。
```

```text
使用 $alluxio-ops-triage 把这些日志、事件和指标整理成一份 Support 升级报告，并明确剩余数据缺口。
```

建议同时提供：

- 事件时间范围和时区；
- 客户影响与严重程度；
- Alluxio、Operator 和相关组件版本；
- 部署模式、访问方式和缓存模式；
- 受影响的 namespace、Pod、主机、节点、路径或 bucket；
- 最近变更；
- 已脱敏的日志、事件、指标、配置或诊断包。

## 强制安全门禁

### 默认只读

诊断请求不会自动执行重启、扩缩容、配置修改、任务重跑、缓存清理、etcd 维护、PVC 删除、数据恢复、写入测试或主机变更。任何生产变更都必须先说明目标、影响、前置条件、失败信号、验证、回滚和观察窗口。

### Properties 修改必须由 Alluxio 专家确认

任何 Alluxio property 修改均属于专家审批范围，包括：

- `*.properties` 文件；
- ConfigMap 或 AlluxioCluster 中的 properties；
- Helm values；
- 环境变量；
- JVM `-D` 参数；
- 组件启动参数中的等效配置。

skill 可以读取、比较并生成待审批方案，但在实际修改前必须展示精确配置项、当前有效值及来源、目标值、影响范围、版本依据、重启或滚动行为、验证和回滚方案。只有用户明确确认“这些具体配置项和值已经由 Alluxio 专家审核批准”后，才能继续执行。一般性的“修复”“优化”或“修改配置”请求不构成该确认。

### 其他关键限制

- 不会在退化中的 Alluxio FUSE 挂载点执行递归 `ls`、`find`、`du` 或全量校验。
- 不会把单一日志关键词或单个阈值直接当作根因。
- 不会在只读诊断中执行 etcd compact、defrag、restore、成员变更或数据卷删除。
- 不会输出或上传凭证、Token、私钥、签名 URL、客户数据路径和内部地址。
- 不会未经明确授权运行可能通过 `sudo` 安装系统包的完整系统采集脚本。

## 离线分析器

对目录或 tar 格式诊断包进行有界、只读、脱敏的初步扫描：

```bash
python3 scripts/analyze_bundle.py /path/to/snapshot.tar.gz \
  --output /tmp/alluxio-bundle-summary.md
```

分析器不会解压 tar 包，会限制文件数量与读取体积，并对常见凭证形式进行脱敏。输出仅用于建立信号清单和下一步假设，不是自动根因结论。

查看全部参数：

```bash
python3 scripts/analyze_bundle.py --help
```

## 仓库结构

```text
alluxio-ops-triage/
├── SKILL.md                       # Skill 入口、路由与全局安全边界
├── agents/openai.yaml             # Codex UI 元数据
├── references/
│   ├── live-kubernetes.md         # 在线 Kubernetes 排障与变更门禁
│   ├── offline-bundle.md          # Diagnostic Snapshot/collectinfo 分析
│   ├── symptom-runbooks.md        # 按症状和组件路由的排障手册
│   ├── etcd-operations.md         # etcd 诊断、容量与受控恢复
│   ├── observability.md           # 指标查询和解释规则
│   ├── report-template.md         # Support 诊断报告模板
│   └── source-map.md              # 官方文档、源码与版本校验入口
└── scripts/
    ├── analyze_bundle.py           # 有界、脱敏的离线分析器
    └── test_analyze_bundle.py      # 回归测试
```

Skill 采用渐进式加载：`SKILL.md` 只保留通用工作流和安全边界，具体场景按需读取对应 reference。

## 验证与开发

运行离线分析器回归测试：

```bash
python3 -m unittest discover -s scripts -p 'test_*.py' -v
```

运行 Codex skill 结构校验：

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-creator/scripts/quick_validate.py" .
```

提交前还应确认：

- `SKILL.md` 中的路由能找到所有 references；
- 新增命令和配置项已按目标版本验证；
- 没有客户数据、密钥、内网地址或诊断产物进入仓库；
- properties 专家审批门禁没有被场景手册绕过。

## 资料来源与维护原则

内容综合自：

- [Alluxio Enterprise AI 官方文档](https://documentation.alluxio.io/ee-ai-en)；
- 与目标版本匹配的 Enterprise 源码；
- Support SOP 中可复用的运维模式；
- [etcd 官方运维文档](https://etcd.io/docs/v3.5/op-guide/maintenance/)。

运行时证据优先于通用手册；版本匹配的官方文档和源码优先于历史 SOP。命令、配置、指标、CRD 字段、默认值和恢复步骤都应根据实际版本重新验证。
