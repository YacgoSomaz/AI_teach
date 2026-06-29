"""
初二物理人教版知识点 seed 脚本

功能：
1. 清除 knowledge_points 表中所有旧的高中物理测试数据
2. 插入初二物理人教版全册知识点
3. 为 default_student 插入 demo 掌握度数据（用于界面展示）

用法（在容器内运行）：
  python scripts/seed_physics_kp.py

或通过 docker exec：
  docker exec -it ai_review_system-api-1 python scripts/seed_physics_kp.py
"""

import asyncio
import random
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.config import settings
from src.models.knowledge_point import KnowledgePoint
from src.models.student_profile import StudentKnowledgeProfile

STUDENT_ID = "default_student"

# ── 初二物理人教版全册知识点 ──────────────────────────────────────────────────
# 结构：(name, chapter, description)
GRADE8_PHYSICS = [
    # ── 上册 ──
    ("机械运动", "第一章 机械运动", "描述物体位置变化的运动"),
    ("参考系与运动的相对性", "第一章 机械运动", "运动和静止是相对的，取决于参考系的选择"),
    ("长度的测量", "第一章 机械运动", "使用刻度尺测量长度，注意估读和单位换算"),
    ("时间的测量", "第一章 机械运动", "使用停表等工具测量时间"),
    ("误差与错误的区别", "第一章 机械运动", "误差不可避免，错误可以避免；多次测量取平均值减小误差"),
    ("速度", "第一章 机械运动", "速度是描述运动快慢的物理量，v = s/t"),
    ("匀速直线运动", "第一章 机械运动", "速度大小和方向都不变的直线运动"),
    ("平均速度", "第一章 机械运动", "一段路程内的路程与时间之比，v̄ = s/t"),

    ("声音的产生与传播", "第二章 声现象", "声音由物体振动产生，需要介质传播，真空不能传声"),
    ("声速", "第二章 声现象", "声音在不同介质中传播速度不同，15°C空气中约340m/s"),
    ("音调、响度和音色", "第二章 声现象", "音调由频率决定，响度由振幅决定，音色由发声体材料和结构决定"),
    ("噪声及其控制", "第二章 声现象", "从声源、传播途径、接收处三方面控制噪声"),
    ("声的利用", "第二章 声现象", "超声波和次声波的应用，如声呐、B超等"),

    ("温度与温度计", "第三章 物态变化", "温度是物体冷热程度的量度，温度计利用液体热胀冷缩原理"),
    ("熔化和凝固", "第三章 物态变化", "晶体有固定熔点，非晶体没有固定熔点；熔化吸热，凝固放热"),
    ("汽化和液化", "第三章 物态变化", "蒸发和沸腾是汽化的两种方式；汽化吸热，液化放热"),
    ("升华和凝华", "第三章 物态变化", "固体直接变气体为升华（吸热），气体直接变固体为凝华（放热）"),
    ("水循环", "第三章 物态变化", "自然界中水的物态变化形成水循环"),

    ("光的直线传播", "第四章 光现象", "光在同种均匀介质中沿直线传播，可解释影子、日食、月食等"),
    ("光速", "第四章 光现象", "光在真空中速度约为3×10⁸ m/s，在不同介质中速度不同"),
    ("光的反射", "第四章 光现象", "反射定律：反射角等于入射角，法线在入射光线和反射光线之间"),
    ("平面镜成像", "第四章 光现象", "平面镜成等大虚像，像与物关于镜面对称"),
    ("光的折射", "第四章 光现象", "光从一种介质进入另一种介质时传播方向发生改变"),
    ("光的色散", "第四章 光现象", "白光通过棱镜分解为红橙黄绿蓝靛紫七种颜色"),

    ("透镜", "第五章 透镜及其应用", "凸透镜对光有会聚作用，凹透镜对光有发散作用"),
    ("凸透镜成像规律", "第五章 透镜及其应用", "物距大于2f成倒立缩小实像；等于2f成等大实像；小于2f成正立放大虚像"),
    ("眼睛与视力矫正", "第五章 透镜及其应用", "近视眼用凹透镜矫正，远视眼用凸透镜矫正"),
    ("照相机、投影仪和放大镜", "第五章 透镜及其应用", "三种光学仪器对应凸透镜成像的三种情况"),

    ("质量", "第六章 质量与密度", "质量是物体所含物质的多少，与状态、形状、位置无关"),
    ("天平的使用", "第六章 质量与密度", "使用天平测量质量，左物右码，游码调平"),
    ("密度", "第六章 质量与密度", "密度是物质的特性，ρ = m/V，单位 kg/m³"),
    ("密度的测量", "第六章 质量与密度", "用天平测质量，用量筒测体积，计算密度"),
    ("密度与物质鉴别", "第六章 质量与密度", "利用密度公式鉴别物质，判断纯度"),

    # ── 下册 ──
    ("力的概念", "第七章 力", "力是物体间的相互作用，用符号F表示，单位牛顿(N)"),
    ("力的三要素与示意图", "第七章 力", "力的大小、方向、作用点称为力的三要素，用力的示意图表示"),
    ("弹力与弹簧测力计", "第七章 力", "弹力由形变产生，弹簧测力计利用弹力测力大小"),
    ("重力", "第七章 力", "重力是地球对物体的吸引力，G = mg，方向竖直向下"),
    ("摩擦力", "第七章 力", "摩擦力分静摩擦力和滑动摩擦力，影响因素：压力大小和接触面粗糙程度"),

    ("牛顿第一定律", "第八章 运动和力", "物体不受力时保持匀速直线运动或静止状态（惯性定律）"),
    ("惯性", "第八章 运动和力", "物体保持原来运动状态的性质，质量越大惯性越大"),
    ("二力平衡", "第八章 运动和力", "两个力大小相等、方向相反、作用在同一直线上、作用在同一物体上"),
    ("力与运动的关系", "第八章 运动和力", "力是改变运动状态的原因，不是维持运动的原因"),

    ("压强", "第九章 压强", "压强是压力与受力面积之比，p = F/S，单位帕斯卡(Pa)"),
    ("增大和减小压强的方法", "第九章 压强", "增大压强：增大压力或减小受力面积；减小压强：减小压力或增大受力面积"),
    ("液体压强", "第九章 压强", "液体压强与深度和密度有关，p = ρgh"),
    ("连通器", "第九章 压强", "连通器中同种液体静止时各处液面等高，应用：茶壶、船闸等"),
    ("大气压强", "第九章 压强", "大气对浸在其中的物体有压强，标准大气压约为1.013×10⁵ Pa"),
    ("流体压强与流速的关系", "第九章 压强", "流速越大，压强越小（伯努利原理的定性说明）"),

    ("浮力", "第十章 浮力", "浮力是液体（气体）对浸入其中物体向上的托力"),
    ("阿基米德原理", "第十章 浮力", "浮力等于物体排开液体的重力，F浮 = ρ液gV排"),
    ("物体的浮沉条件", "第十章 浮力", "上浮：F浮>G；漂浮：F浮=G；下沉：F浮<G"),
    ("浮力的应用", "第十章 浮力", "轮船、潜水艇、气球、密度计等都利用了浮力原理"),

    ("功", "第十一章 功和机械能", "力与力的方向上移动距离的乘积，W = Fs，单位焦耳(J)"),
    ("功率", "第十一章 功和机械能", "单位时间内做的功，P = W/t，单位瓦特(W)"),
    ("动能和势能", "第十一章 功和机械能", "动能与速度和质量有关；重力势能与高度和质量有关；弹性势能与形变有关"),
    ("机械能及其转化", "第十一章 功和机械能", "动能和势能之间可以相互转化，总量守恒"),

    ("杠杆", "第十二章 简单机械", "杠杆平衡条件：F₁×l₁ = F₂×l₂（力×力臂相等）"),
    ("滑轮", "第十二章 简单机械", "定滑轮改变力的方向，动滑轮省一半力；滑轮组可省力且改变方向"),
    ("机械效率", "第十二章 简单机械", "有用功与总功之比，η = W有用/W总，机械效率总小于1"),
]


async def seed(session: AsyncSession) -> None:
    print("▶ 开始 seed 初二物理知识点…")

    # 1. 清除 default_student 的所有旧掌握度记录
    await session.execute(
        delete(StudentKnowledgeProfile).where(
            StudentKnowledgeProfile.student_id == STUDENT_ID
        )
    )
    print("  ✓ 已清除 default_student 旧掌握度记录")

    # 2. 清除所有非初二/非人教版的物理知识点（高中测试数据）
    result = await session.execute(
        select(KnowledgePoint).where(
            KnowledgePoint.subject == "物理",
            KnowledgePoint.textbook_version != "人教版",
        )
    )
    old_kps = result.scalars().all()
    for kp in old_kps:
        await session.delete(kp)
    print(f"  ✓ 已删除 {len(old_kps)} 条旧知识点")

    # 3. 检查现有初二知识点（避免重复插入）
    existing = (
        await session.execute(
            select(KnowledgePoint.name).where(
                KnowledgePoint.subject == "物理",
                KnowledgePoint.textbook_version == "人教版",
            )
        )
    ).scalars().all()
    existing_names = set(existing)

    # 4. 插入初二物理人教版知识点
    new_kps: list[KnowledgePoint] = []
    for name, chapter, description in GRADE8_PHYSICS:
        if name in existing_names:
            continue
        kp = KnowledgePoint(
            id=uuid.uuid4(),
            name=name,
            subject="物理",
            grade="八年级",
            chapter=chapter,
            description=description,
            textbook_version="人教版",
            is_active=True,
        )
        session.add(kp)
        new_kps.append(kp)

    await session.flush()
    print(f"  ✓ 已插入 {len(new_kps)} 个初二物理知识点")

    # 5. 为 default_student 插入 demo 掌握度数据
    # 前几个知识点给低掌握度，模拟"需要复习"的状态
    all_kps = (
        await session.execute(
            select(KnowledgePoint).where(
                KnowledgePoint.subject == "物理",
                KnowledgePoint.grade == "八年级",
                KnowledgePoint.textbook_version == "人教版",
                KnowledgePoint.is_active.is_(True),
            )
        )
    ).scalars().all()

    random.seed(42)
    profiles_added = 0
    for i, kp in enumerate(all_kps):
        # 前12个给低掌握度（会出现在复习列表里），后面的随机
        if i < 12:
            mastery = round(random.uniform(0.05, 0.38), 2)
            priority = "high"
        elif i < 24:
            mastery = round(random.uniform(0.40, 0.68), 2)
            priority = "medium"
        else:
            mastery = round(random.uniform(0.70, 0.95), 2)
            priority = "low"

        error_count = random.randint(1, 8) if mastery < 0.5 else random.randint(0, 3)
        appear_count = error_count + random.randint(2, 10)

        profile = StudentKnowledgeProfile(
            student_id=STUDENT_ID,
            knowledge_point_id=kp.id,
            mastery_score=mastery,
            review_priority=priority,
            error_count=error_count,
            appear_count=appear_count,
            last_reviewed_at=datetime.now(timezone.utc),
        )
        session.add(profile)
        profiles_added += 1

    await session.commit()
    print(f"  ✓ 已插入 {profiles_added} 条 default_student 掌握度记录")
    print("✅ Seed 完成！")


async def main() -> None:
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        await seed(session)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
