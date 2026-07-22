"""
技能注册表 — 腾讯频道 Community 能力集成

所有腾讯频道 API 工具 (45个):
  - 频道管理: 创建/修改/头像/加入设置/版块管理/分享链接解析
  - 成员管理: 列表/角色/禁言/踢人/身份组/用户信息
  - 帖子: 发布/编辑/删除/置顶/精华/搜索/详情
  - 评论回复: 评论/回复/点赞
  - 消息通知: 私信/精华帖推送
  - 互动: 点赞/取消点赞

使用 tencent-channel-cli 命令行工具调用。
"""

import asyncio, json, os, subprocess, tempfile
from pathlib import Path
from typing import Optional

# CLI 路径
TCC_CLI = "tencent-channel-cli"


class ChannelSkill:
    """腾讯频道社区管理技能"""

    # ---- 频道管理 ----

    @staticmethod
    async def get_share_info(share_url: str) -> dict:
        return await ChannelSkill._run("manage", "get-share-info", {"share_url": share_url})

    @staticmethod
    async def get_guild_channel_list(guild_id: str) -> dict:
        return await ChannelSkill._run("manage", "get-guild-channel-list", {"guild_id": guild_id})

    @staticmethod
    async def create_guild(name: str, **kwargs) -> dict:
        return await ChannelSkill._run("manage", "create-guild", {"name": name, **kwargs})

    @staticmethod
    async def update_guild_info(guild_id: str, **kwargs) -> dict:
        return await ChannelSkill._run("manage", "update-guild-info", {"guild_id": guild_id, **kwargs})

    @staticmethod
    async def create_channel(guild_id: str, name: str, **kwargs) -> dict:
        return await ChannelSkill._run("manage", "create-channel", {"guild_id": guild_id, "name": name, **kwargs})

    @staticmethod
    async def modify_channel(guild_id: str, channel_id: str, name: str) -> dict:
        return await ChannelSkill._run("manage", "modify-channel", {"guild_id": guild_id, "channel_id": channel_id, "name": name})

    @staticmethod
    async def delete_channel(guild_id: str, channel_ids: list[str]) -> dict:
        return await ChannelSkill._run("manage", "delete-channel", {"guild_id": guild_id, "channel_ids": channel_ids})

    @staticmethod
    async def upload_guild_avatar(guild_id: str, avatar_path: str) -> dict:
        return await ChannelSkill._run("manage", "upload-guild-avatar", {"guild_id": guild_id, "avatar_path": avatar_path})

    @staticmethod
    async def get_guild_info(guild_id: str) -> dict:
        return await ChannelSkill._run("manage", "get-guild-info", {"guild_id": guild_id})

    @staticmethod
    async def get_join_guild_setting(guild_id: str) -> dict:
        return await ChannelSkill._run("manage", "get-join-guild-setting", {"guild_id": guild_id})

    @staticmethod
    async def update_join_guild_setting(guild_id: str, **kwargs) -> dict:
        return await ChannelSkill._run("manage", "update-join-guild-setting", {"guild_id": guild_id, **kwargs})

    # ---- 搜索 ----

    @staticmethod
    async def search_guild_content(keyword: str, scope: str = "all", **kwargs) -> dict:
        return await ChannelSkill._run("manage", "search-guild-content", {"keyword": keyword, "scope": scope, **kwargs})

    @staticmethod
    async def get_search_guild_feed(guild_id: str, keyword: str, **kwargs) -> dict:
        return await ChannelSkill._run("feed", "search-guild-feeds", {"guild_id": guild_id, "keyword": keyword, **kwargs})

    # ---- 成员管理 ----

    @staticmethod
    async def get_guild_member_list(guild_id: str, **kwargs) -> dict:
        return await ChannelSkill._run("member", "get-guild-member-list", {"guild_id": guild_id, **kwargs})

    @staticmethod
    async def get_user_info(guild_id: str, user_id: str) -> dict:
        return await ChannelSkill._run("member", "get-user-info", {"guild_id": guild_id, "user_id": user_id})

    @staticmethod
    async def kick_guild_member(guild_id: str, user_id: str, **kwargs) -> dict:
        return await ChannelSkill._run("member", "kick-guild-member", {"guild_id": guild_id, "user_id": user_id, **kwargs})

    @staticmethod
    async def modify_member_shut_up(guild_id: str, user_id: str, duration: int) -> dict:
        return await ChannelSkill._run("member", "modify-member-shut-up", {"guild_id": guild_id, "user_id": user_id, "duration": duration})

    @staticmethod
    async def change_role_member(guild_id: str, role_id: str, user_ids: list[str]) -> dict:
        return await ChannelSkill._run("member", "change-role-member", {"guild_id": guild_id, "role_id": role_id, "user_ids": user_ids})

    @staticmethod
    async def create_guild_role_group(guild_id: str, name: str, **kwargs) -> dict:
        return await ChannelSkill._run("member", "create-guild-role-group", {"guild_id": guild_id, "name": name, **kwargs})

    @staticmethod
    async def modify_guild_role_group(guild_id: str, role_id: str, **kwargs) -> dict:
        return await ChannelSkill._run("member", "modify-guild-role-group", {"guild_id": guild_id, "role_id": role_id, **kwargs})

    # ---- 帖子 ----

    @staticmethod
    async def publish_feed(guild_id: str, channel_id: str, content: str, **kwargs) -> dict:
        return await ChannelSkill._run("feed", "publish-feed", {"guild_id": guild_id, "channel_id": channel_id, "content": content, **kwargs})

    @staticmethod
    async def get_feed_detail(guild_id: str, feed_id: str) -> dict:
        return await ChannelSkill._run("feed", "get-feed-detail", {"guild_id": guild_id, "feed_id": feed_id})

    @staticmethod
    async def get_guild_feeds(guild_id: str, **kwargs) -> dict:
        return await ChannelSkill._run("feed", "get-guild-feeds", {"guild_id": guild_id, **kwargs})

    @staticmethod
    async def get_channel_timeline_feeds(guild_id: str, channel_id: str, **kwargs) -> dict:
        return await ChannelSkill._run("feed", "get-channel-timeline-feeds", {"guild_id": guild_id, "channel_id": channel_id, **kwargs})

    @staticmethod
    async def alter_feed(guild_id: str, feed_id: str, **kwargs) -> dict:
        return await ChannelSkill._run("feed", "alter-feed", {"guild_id": guild_id, "feed_id": feed_id, **kwargs})

    @staticmethod
    async def del_feed(guild_id: str, feed_id: str) -> dict:
        return await ChannelSkill._run("feed", "del-feed", {"guild_id": guild_id, "feed_id": feed_id})

    @staticmethod
    async def top_feed_action(guild_id: str, feed_id: str, action: str, **kwargs) -> dict:
        return await ChannelSkill._run("feed", "top-feed-action", {"guild_id": guild_id, "feed_id": feed_id, "action": action, **kwargs})

    @staticmethod
    async def batch_essence(guild_id: str, feed_ids: list[str], set_essence: bool) -> dict:
        return await ChannelSkill._run("feed", "batch-essence", {"guild_id": guild_id, "feed_ids": feed_ids, "set_essence": set_essence})

    # ---- 评论与回复 ----

    @staticmethod
    async def do_comment(guild_id: str, feed_id: str, content: str, **kwargs) -> dict:
        return await ChannelSkill._run("feed", "do-comment", {"guild_id": guild_id, "feed_id": feed_id, "content": content, **kwargs})

    @staticmethod
    async def get_feed_comments(guild_id: str, feed_id: str, **kwargs) -> dict:
        return await ChannelSkill._run("feed", "get-feed-comments", {"guild_id": guild_id, "feed_id": feed_id, **kwargs})

    @staticmethod
    async def do_reply(guild_id: str, comment_id: str, content: str, **kwargs) -> dict:
        return await ChannelSkill._run("feed", "do-reply", {"guild_id": guild_id, "comment_id": comment_id, "content": content, **kwargs})

    @staticmethod
    async def get_next_page_replies(guild_id: str, comment_id: str, **kwargs) -> dict:
        return await ChannelSkill._run("feed", "get-next-page-replies", {"guild_id": guild_id, "comment_id": comment_id, **kwargs})

    # ---- 消息通知 ----

    @staticmethod
    async def push_group_normal_dm_msg(guild_id: str, user_id: str, content: str) -> dict:
        return await ChannelSkill._run("notify", "push-group-normal-dm-msg", {"guild_id": guild_id, "user_id": user_id, "content": content})

    @staticmethod
    async def push_essence_feed(guild_id: str, feed_id: str) -> dict:
        return await ChannelSkill._run("notify", "push-essence-feed", {"guild_id": guild_id, "feed_id": feed_id})

    @staticmethod
    async def push_qq_msg(content: str) -> dict:
        return await ChannelSkill._run("notify", "push-qq-msg", {"content": content})

    # ---- 互动 ----

    @staticmethod
    async def do_feed_prefer(guild_id: str, feed_id: str, prefer: bool) -> dict:
        return await ChannelSkill._run("feed", "do-feed-prefer", {"guild_id": guild_id, "feed_id": feed_id, "prefer": prefer})

    @staticmethod
    async def do_like(guild_id: str, comment_id: str, like: bool) -> dict:
        return await ChannelSkill._run("feed", "do-like", {"guild_id": guild_id, "comment_id": comment_id, "like": like})

    # ---- 用户操作 ----

    @staticmethod
    async def join_guild(guild_id: str, **kwargs) -> dict:
        return await ChannelSkill._run("manage", "join-guild", {"guild_id": guild_id, **kwargs})

    @staticmethod
    async def leave_guild(guild_id: str) -> dict:
        return await ChannelSkill._run("manage", "leave-guild", {"guild_id": guild_id})

    @staticmethod
    async def get_my_join_guild_info() -> dict:
        return await ChannelSkill._run("manage", "get-my-join-guild-info", {})

    # ---- 内部实现 ----

    @staticmethod
    async def _run(domain: str, action: str, params: dict) -> dict:
        """执行 CLI 命令并返回 JSON"""
        cmd = [TCC_CLI, domain, action, "--json"]

        # 用 flag 传参
        for k, v in params.items():
            if isinstance(v, bool):
                if v:
                    cmd.append(f"--{k.replace('_', '-')}")
            elif isinstance(v, list):
                cmd.append(f"--{k.replace('_', '-')}")
                cmd.append(",".join(str(x) for x in v))
            else:
                cmd.append(f"--{k.replace('_', '-')}")
                cmd.append(str(v))

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=60
            )

            if proc.returncode != 0:
                err = stderr.decode("utf-8", errors="replace")
                print(f"[ChannelSkill] CLI 错误: {err}")
                return {"error": err, "ret_code": proc.returncode}

            output = stdout.decode("utf-8", errors="replace").strip()
            try:
                return json.loads(output)
            except json.JSONDecodeError:
                return {"raw": output}

        except asyncio.TimeoutError:
            return {"error": "命令超时"}
        except FileNotFoundError:
            return {"error": "tencent-channel-cli 未安装，请运行: npm install -g tencent-channel-cli"}


class SkillRegistry:
    """技能注册表 — 管理所有可用技能"""

    def __init__(self):
        self._skills = {}

    def register(self, name: str, skill_class):
        self._skills[name] = skill_class

    def get(self, name: str):
        return self._skills.get(name)

    def list_skills(self) -> list[str]:
        return list(self._skills.keys())


# 全局注册表
registry = SkillRegistry()
registry.register("channel", ChannelSkill)