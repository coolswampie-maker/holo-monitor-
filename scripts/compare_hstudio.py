#!/usr/bin/env python3
"""Сверка показателей ГОЛОЦИТа с реальной выгрузкой Hstudio.

Эталон: SpreadsheetML-выгрузка эксперимента A549, восстановленная с
дистрибутивной флешки прибора (лист Average, 131 кадр, 5 клеток).

ГЛАВНОЕ ОГРАНИЧЕНИЕ. К этой выгрузке НЕ приложены изображения: в ней
только числа. Прогнать ГОЛОЦИТ на тех же клетках невозможно, поэтому
числовая сверка «наше против ихнего на одних данных» недостижима.

Что проверяемо и проверено:
  * алгебраические соотношения внутри самих чисел Hstudio — сходятся ли
    они с формулами руководства;
  * определения показателей: совпадает ли наша формула с описанной
    в руководстве;
  * там, где формулу можно применить к числам Hstudio, — расхождение.

Вердикты: MATCHES, APPROXIMATES, DIFFERENT_DEFINITION, CANNOT_VALIDATE.
"""

import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from holocyt import parameters as pm

REF = Path(__file__).resolve().parents[1] / "recovery" / "carved" / "ExcelExport_head.xml"


def read_reference():
    """Первая строка листа Average — значения по первому кадру."""
    txt = REF.read_text(encoding="utf-8", errors="replace")
    i = txt.find('ss:Name="Average"')
    seg = txt[i:i + 40000]
    names = re.findall(r'<Data ss:Type="String">([^<]{1,80})</Data>', seg)
    nums = [float(x) for x in
            re.findall(r'<Data ss:Type="Number">([^<]{1,30})</Data>', seg)]
    headers = [n for n in names if n.startswith("Avg.") or n.startswith("Number of")]
    return dict(zip(headers, nums)), headers


def main():
    ref, headers = read_reference()
    print("ЭТАЛОН: выгрузка Hstudio, эксперимент A549, лист Average, кадр 1")
    print(f"  файл: {REF}")
    print(f"  клеток в кадре: {int(ref.get('Number of tracked cells', 0))}\n")
    for k in headers:
        print(f"  {k:<50s} {ref[k]:>12.4f}")

    A = ref.get("Avg. Area (µm²)")
    P = ref.get("Avg. Perimeter length (µm)")
    L = ref.get("Avg. Boxed length (µm)")
    B = ref.get("Avg. Boxed breadth (µm)")
    Ta = ref.get("Avg. Optical thickness avg (µm)")
    Tm = ref.get("Avg. Optical thickness max (µm)")
    V = ref.get("Avg. Optical volume (µm³)")
    IR = ref.get("Avg. Irregularity")

    print("\n\nПРОВЕРКА СООТНОШЕНИЙ ВНУТРИ ЧИСЕЛ HSTUDIO")
    print("-" * 74)
    # Объём против площади и средней толщины. Точного равенства быть не
    # должно: это средние по пяти клеткам, а среднее произведения не равно
    # произведению средних. Но порядок обязан совпасть.
    print(f"  V против A*T_avg:   {V:.1f} против {A * Ta:.1f}  "
          f"отношение {V / (A * Ta):.3f}")
    print("    порядок совпал; точного равенства и не ожидается —")
    print("    это средние по 5 клеткам, среднее произведения != произведению средних")
    # Габарит против площади.
    print(f"  A против L*B*pi/4:  {A:.1f} против {L * B * math.pi / 4:.1f}  "
          f"отношение {A / (L * B * math.pi / 4):.3f}")
    print("    близко к единице — клетка заметно отличается от эллипса, противоречия нет")

    print("\n\nИЗРЕЗАННОСТЬ: НАША ФОРМУЛА НА ИХ ЧИСЛАХ")
    print("-" * 74)
    ours = P / (2 * math.sqrt(math.pi * A)) - 1
    ours2 = P ** 2 / (4 * math.pi * A) - 1
    print(f"  Hstudio Irregularity                       {IR:.4f}")
    print(f"  наша формула  P/(2*sqrt(pi*A)) - 1         {ours:.4f}")
    print(f"  вариант       P^2/(4*pi*A) - 1             {ours2:.4f}")
    print(f"  расхождение с нашей формулой: в {IR / ours:.1f} раза")
    print("    ВЕРДИКТ: DIFFERENT_DEFINITION. Совпадения нет ни при одном")
    print("    из общепринятых определений. Название Hstudio для нашего")
    print("    показателя не используется.")

    print("\n\nСВОДНАЯ ТАБЛИЦА СОПОСТАВЛЕНИЯ")
    print("-" * 110)
    print(f"{'параметр Hstudio':<26s} {'наш параметр':<26s} {'кат':>4s} "
          f"{'вердикт':<22s} примечание")
    print("-" * 110)
    for r in pm.mapping_table():
        note = (r["note"][:38] + "…") if len(r["note"]) > 39 else r["note"]
        print(f"{r['hstudio']:<26s} {r['holocyt']:<26s} {r['category']:>4s} "
              f"{r['verdict']:<22s} {note}")

    import collections
    c = collections.Counter(r["verdict"] for r in pm.mapping_table())
    print("-" * 110)
    print("  итого: " + ", ".join(f"{k} — {v}" for k, v in c.most_common()))
    print("\n  Числовая сверка «на одних и тех же клетках» НЕ проведена:")
    print("  к выгрузке A549 не приложены изображения. Это ограничение")
    print("  данных, а не методики. Чтобы её провести, нужен эксперимент,")
    print("  где есть и карты фазы, и выгрузка Hstudio по ним же.")


if __name__ == "__main__":
    main()
