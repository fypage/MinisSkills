# Minis 技能安装说明

## 适用范围

本说明适用于仓库中的公开技能：

- `image-generator`
- `github-sync-helper`
- `cloudflare-dns`
- `self-improving-agent`
- `skill-creator`
- `unrestricted`

Minis 的技能目录为：

```text
/var/minis/skills/<skill-name>/
```

每个技能目录必须直接包含 `SKILL.md`，不要多套一层目录。

## 方法一：克隆整个仓库

```bash
cd /var/minis/workspace
git clone https://github.com/fypage/MinisSkills.git

for skill in image-generator github-sync-helper cloudflare-dns self-improving-agent skill-creator unrestricted; do
  rm -rf "/var/minis/skills/$skill"
  cp -R "/var/minis/workspace/MinisSkills/$skill" "/var/minis/skills/$skill"
done
```

只安装一个技能，例如 `image-generator`：

```bash
rm -rf /var/minis/skills/image-generator
cp -R /var/minis/workspace/MinisSkills/image-generator /var/minis/skills/image-generator
```

## 方法二：下载 ZIP

1. 打开仓库页面，选择 **Code → Download ZIP**。
2. 解压 ZIP。
3. 将需要的技能目录复制到 `/var/minis/skills/`。
4. 确认最终路径类似：

```text
/var/minis/skills/image-generator/SKILL.md
```

错误示例（多套了一层目录）：

```text
/var/minis/skills/image-generator/MinisSkills-main/image-generator/SKILL.md
```

## 方法三：安装单个公开技能

GitHub 不原生支持只 clone 一个目录，可使用 sparse checkout：

```bash
cd /var/minis/workspace
rm -rf MinisSkills-one
git clone --filter=blob:none --no-checkout https://github.com/fypage/MinisSkills.git MinisSkills-one
cd MinisSkills-one
git sparse-checkout init --cone
git sparse-checkout set image-generator
git checkout main
rm -rf /var/minis/skills/image-generator
cp -R image-generator /var/minis/skills/image-generator
```

把 `image-generator` 换成目标技能名即可。

## 更新技能

如果保留了完整克隆：

```bash
cd /var/minis/workspace/MinisSkills
git pull --ff-only
rm -rf /var/minis/skills/image-generator
cp -R image-generator /var/minis/skills/image-generator
```

更新前如修改过本地技能，请先备份或比较差异，避免覆盖自己的改动。

## 验证安装

```bash
test -f /var/minis/skills/image-generator/SKILL.md && echo OK
find /var/minis/skills/image-generator -maxdepth 2 -type f | sort
```

有 Python 脚本的技能可检查语法：

```bash
find /var/minis/skills/image-generator -name '*.py' -exec python3 -m py_compile {} \;
```

有 Shell 脚本的技能可检查语法：

```bash
find /var/minis/skills/github-sync-helper -name '*.sh' -exec sh -n {} \;
```

安装后重新打开聊天或重启 Minis，让技能列表重新加载。可在 [Settings → Skills](minis://settings/skills) 查看技能。

## 依赖与环境变量

技能的具体依赖以各自 `SKILL.md` 为准。常见配置入口：

- Provider：[Settings → Providers](minis://settings/providers)
- Model Groups：[Settings → Model Groups](minis://settings/model-groups)
- Environment Variables：[Settings → Environments](minis://settings/environments)
- Permissions：[Settings → Permissions](minis://settings/permissions)

不要把 API Key、Token、Cookie 或密码写入技能源码或提交到 GitHub。

## 卸载

```bash
rm -rf /var/minis/skills/<skill-name>
```

删除后重新打开聊天或重启 Minis。

## 私有技能

`blackforge-reverse-lab` 和 `juyue-rule-dev` 使用独立私有仓库维护，不包含在本公开仓库中。私有仓库必须使用有访问权限的 GitHub 账号或 Token 克隆，不要在命令行、聊天记录或脚本中直接写明文 Token。
