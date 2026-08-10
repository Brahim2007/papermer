# نتائج مصفوفة الاسترجاع الخارجية B0–B7

**تاريخ التشغيل:** 2026-08-10
**البروتوكول:** `external_full_corpus_B0_B7_v1`
**الحالة:** جزئية؛ SciFact مكتمل، وSciDocs مكتمل حتى B6، بينما ينتظر SciDocs-B7
وLitSearch-B2/B3/B5/B6/B7 رفع حد الإنفاق في Modal. لا تعد هذه النسخة جدول الورقة
النهائي بعد.

## النتائج المنفذة

| Dataset | Run | nDCG@10 | MAP | Recall@100 | p95 latency (ms) | Runtime | الحالة |
|---|---|---:|---:|---:|---:|---|---|
| SciFact | B0 TF-IDF | 0.6418 | 0.5988 | 0.8916 | 24.3 | Modal L4 | مكتمل |
| SciFact | B1 BM25 | 0.6639 | 0.6267 | 0.8792 | 15.0 | Modal L4 | مكتمل |
| SciFact | B2 SPECTER2 | 0.6455 | 0.6086 | **0.9597** | 22.0 | Modal L4 | مكتمل |
| SciFact | B3 Hybrid-RRF | **0.6962** | **0.6582** | 0.9587 | 34.8 | Modal L4 | مكتمل |
| SciFact | B4 graph | — | — | — | — | Modal L4 | N/A: لا توجد حواف في المصدر |
| SciFact | B5 tri-channel | — | — | — | — | Modal L4 | N/A: لا توجد حواف في المصدر |
| SciFact | B6 B3 + cross-encoder | 0.6923 | 0.6523 | 0.9587 | 322.9 | Modal L4 | مكتمل |
| SciFact | B7 B5 + cross-encoder | — | — | — | — | Modal L4 | N/A: لا توجد حواف في المصدر |
| SciDocs | B0 TF-IDF | 0.1472 | 0.1002 | 0.3518 | 146.9 | Modal L4 | مكتمل |
| SciDocs | B1 BM25 | 0.1542 | 0.1051 | 0.3518 | 58.0 | Modal L4 | مكتمل |
| SciDocs | B2 SPECTER2 | 0.1731 | 0.1205 | 0.4349 | 31.4 | Modal L4 | مكتمل |
| SciDocs | B3 Hybrid-RRF | 0.1892 | 0.1318 | 0.4354 | 82.2 | Modal L4 | مكتمل |
| SciDocs | B4 graph | 0.1421 | 0.1067 | 0.4610 | 55.3 | Modal L4 | مكتمل |
| SciDocs | B5 tri-channel | **0.1980** | **0.1445** | **0.5152** | 94.9 | Modal L4 | مكتمل |
| SciDocs | B6 B3 + cross-encoder | 0.1702 | 0.1197 | 0.4354 | 367.1 | Modal L4 | مكتمل |
| SciDocs | B7 B5 + cross-encoder | — | — | — | — | — | ينتظر رفع spend limit |
| LitSearch | B0 TF-IDF | 0.3145 | 0.2778 | 0.7073 | 798.1 | local CPU | مكتمل |
| LitSearch | B1 BM25 | **0.3998** | **0.3636** | 0.7210 | 192.6 | local CPU | مكتمل |
| LitSearch | B2 SPECTER2 | — | — | — | — | — | ينتظر رفع spend limit |
| LitSearch | B3 Hybrid-RRF | — | — | — | — | — | — | ينتظر رفع spend limit |
| LitSearch | B4 graph | 0.1736 | 0.1348 | **0.7525** | 258.4 | local CPU | مكتمل |
| LitSearch | B5 tri-channel | — | — | — | — | — | ينتظر رفع spend limit |
| LitSearch | B6 B3 + cross-encoder | — | — | — | — | — | ينتظر رفع spend limit |
| LitSearch | B7 B5 + cross-encoder | — | — | — | — | — | ينتظر رفع spend limit |

هذه النتائج ناتجة من qrels الحقيقية. جرى التحقق من SHA-256 لكل ملف B مكتمل بعد
تنزيله من Modal. لا يصبح الجدول جدول الورقة الرئيسي حتى اكتمال الخلايا المعلّقة
وتشغيل اختبارات الدلالة والثقة. أرقام latency وصفية لبيئة Runtime المبينة ولا يجوز
مقارنتها بين صفوف Modal والـCPU كقياس سرعة عادل.

## تفسير أولي لا يسبق الأدلة

- BM25 يتفوق على TF-IDF في nDCG@10 في المجموعات الثلاث.
- يرفع B3 في SciFact قيمة nDCG@10 من 0.6639 لـBM25 إلى 0.6962، بينما لا تحسن
  إعادة الترتيب B6 النتيجة فوق B3 في هذا الإعداد.
- في SciDocs يحقق B5 أفضل القيم المتاحة: nDCG@10 = 0.1980 وRecall@100 = 0.5152.
  هذا وصف أولي يحتاج اختبار دلالة paired على الاستعلامات، وليس ادعاء تفوق نهائياً.
- الرسم منفرداً يرفع تغطية SciDocs وLitSearch في العمق 100، لكنه يخفض جودة أعلى
  القائمة. هذا يدعم اختبار فرضية B5: استخدام الرسم كقناة توسيع داخل RRF، لا كبديل
  للنص.
- لا يصح تشغيل graph فارغ في SciFact؛ لذلك B4 وB5 وB7 غير منطبقة ما لم يُنشأ
  إصدار جديد من corpus بإثراء استشهادي مسجل. B2/B3/B6 تبقى قابلة للتطبيق.

## تغطية الرسم

| Dataset | كل الحواف | الحواف الداخلية | معدل الحواف الداخلية | تغطية وثائق لها حواف |
|---|---:|---:|---:|---:|
| SciFact | 0 | 0 | 0% | 0% |
| SciDocs | 218,316 | 20,825 | 9.54% | 95.51% |
| LitSearch | 344,703 | 344,703 | 100% | 73.60% |

## تشغيل Modal والاستئناف

اختبار CPU الفعلي لـSPECTER2 على الجهاز الحالي استغرق 17.66 ثانية لترميز 32 وثيقة
(نحو 0.55 ثانية/وثيقة، CPU فقط وأربعة threads). بالتقريب، ترميز 95,023 وثيقة في
المعايير الثلاثة يستغرق نحو 14.6 ساعة قبل استعلامات B2/B3/B5 وإعادة ترتيب B6/B7.
الـVPS ذو نواتين لن يسرّع هذه المرحلة.

أُعد المشغّل `experiments/modal_external_matrix.py` على NVIDIA L4 مع صورة مثبتة
الإصدارات، وحد ساعتين، وVolume دائم، وscale-to-zero. تحقق فحص البداية من
`NVIDIA L4` و`torch 2.6.0+cu124`. أضيفت قابلية استئناف تتحقق من هوية البروتوكول
والبيانات قبل تجاوز أي run مكتمل.

توقفت محاولة الاستئناف الأخيرة قبل تخصيص GPU لأن مساحة العمل تجاوزت spend limit.
بعد رفع الحد يستأنف الأمر نفسه من SciDocs-B7، ثم يبني LitSearch cache ويكمل خلاياه:

```powershell
$env:Path = "$env:APPDATA\Python\Python313\Scripts;$env:Path"
$env:PYTHONUTF8 = "1"
modal run --detach --timestamps experiments\modal_external_matrix.py
```

لا تُرفع النتائج إلى Git؛ تحفظ المدونات والـcaches والـrankings خارج Git، وتنشر
manifests والجداول المشتقة فقط. يجب عدم استبدال النموذج أو تغيير العمق داخل run IDs
الحالية.

## آثار التشغيل

- `results/external/beir-scifact/matrix_manifest.json`
- `results/external/beir-scidocs/matrix_manifest.json`
- `results/external/litsearch/matrix_manifest.json`
- `artifacts/modal_external_matrix_v1/output/` (تنزيل Modal المتحقق؛ خارج Git)

كل نتيجة مفصلة تحفظ per-query rankings والمقاييس وSHA-256 في مجلد `results/`
المستبعد من Git، بينما تبقى هذه الوثيقة هي الملخص القابل للمراجعة.
