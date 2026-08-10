# نشر PaperMetrix على VPS

هذا المسار مخصص لخادم Ubuntu 24.04 بذاكرة 8 GB ونواتين. التطبيق وقاعدة Redis
وCaddy تعمل داخل حاويات، بينما PostgreSQL يبقى خدمة خارجية مُدارة. لا توجد
قاعدة PostgreSQL عامة داخل ملف الإنتاج.

## 1. ما قبل النشر

1. أنشئ سجل DNS من نوع `A` للنطاق إلى عنوان الخادم. أضف `AAAA` فقط إذا كان
   IPv6 يعمل فعليًا.
2. افتح المنافذ `22/tcp` و`80/tcp` و`443/tcp` و`443/udp` فقط. لا تفتح Redis
   أو PostgreSQL.
3. ثبّت Docker Engine وDocker Compose plugin من مستودع Docker الرسمي.
4. استبدل جميع مفاتيح API وكلمات المرور التي ظهرت سابقًا في محادثة أو سجل.
   حذفها من ملف لا يلغي صلاحيتها.
5. ابدأ بمستودع GitHub خاص، ثم اجعله عامًا فقط بعد نجاح فحص الأسرار لتاريخ
   Git كاملًا ومراجعة تراخيص البيانات والنماذج.

## 2. إعداد البيئة

من جذر المشروع:

```bash
cp .env.production.example .env.production
chmod 600 .env.production
openssl rand -base64 48
```

ضع القيمة العشوائية في `DJANGO_SECRET_KEY`، وأنشئ كلمة Redis مستقلة، ثم املأ
النطاق والبريد واتصال PostgreSQL والمفاتيح الخارجية. لا تستخدم قيمة اختبار CI
في الإنتاج. إذا احتوت كلمة Redis على رموز خاصة، استخدم ترميز URL لها داخل
روابط Celery وDjango cache.

تحقق دون طباعة القيم السرية:

```bash
sh deploy/check_env.sh .env.production
docker compose --env-file .env.production -f compose.production.yaml config --quiet
```

## 3. الإطلاق الأول

انسخ ملفي cache المسجلين إلى مجلد `artifacts/` على الخادم قبل البناء، مع
التحقق من checksum الموجود في manifest البحثي. الحد الأدنى للبحث الدلالي هو:

```text
artifacts/paper_recommendation_scope_v2.specter2.npz
artifacts/paper_recommendation_scope_v2.specter2.json
```

هذه الملفات خارج Git عمدًا. إذا غاب أحدهما يبقى البحث متاحًا عبر BM25 +
TF-IDF، وتعرض الواجهة أنه وضع احتياطي بدل الادعاء باستخدام SPECTER2.

```bash
sh deploy/vps_update.sh
docker compose --env-file .env.production -f compose.production.yaml exec web \
  python manage.py createsuperuser
```

Caddy يطلب شهادة TLS ويجددها تلقائيًا، لذلك يجب إبقاء مجلدي `caddy_data`
و`caddy_config`. افحص:

```bash
curl -fsS https://YOUR_DOMAIN/healthz/
curl -fsS https://YOUR_DOMAIN/readyz/
docker compose --env-file .env.production -f compose.production.yaml ps
docker compose --env-file .env.production -f compose.production.yaml logs --tail=200
```

`healthz` يثبت أن العملية حية، و`readyz` يختبر اتصال قاعدة البيانات. لا يحتوي
أي منهما على معلومات سرية.

## 4. التحديث والتراجع

قبل كل إطلاق: أنشئ نسخة قاعدة بيانات، اسحب tag أو commit مراجَعًا، ثم شغّل:

```bash
sh deploy/backup_database.sh
sh deploy/vps_update.sh
```

استخدم إصدارات Git موقّعة أو tags واضحة. للتراجع، انتقل إلى tag السابق وأعد
البناء. لا تعكس migration مدمرة تلقائيًا؛ استعد نسخة قاعدة البيانات عند
الحاجة وبعد نافذة صيانة.

الاستعادة مقيدة بتأكيد صريح:

```bash
RESTORE_CONFIRM=restore-papermetrix \
  sh deploy/restore_database.sh backups/papermetrix-TIMESTAMP.dump
```

اختبر الاستعادة دوريًا في قاعدة منفصلة. النسخة غير مشفرة محليًا، لذا خزّنها
في مساحة مشفرة ومقيدة الوصول، وانقل نسخة خارج الخادم.

## 5. الأحمال البحثية

صورة الويب الدلالية تحمل PyTorch وSPECTER2 وتعمل بعامل Gunicorn واحد كي لا
تكرر النموذج في الذاكرة. يبدأ warm-up خلفيًا بعد تشغيل العامل؛ قد يستغرق
التحميل الأول عشرات الثواني على CPU، بينما تكون الاستعلامات الدافئة أسرع
بكثير. تبقى إعادة بناء embeddings وأدوات التجارب في profile مستقل:

```bash
docker compose --env-file .env.production -f compose.production.yaml \
  --profile research run --rm research python -m experiments.YOUR_COMMAND
```

على نواتين و8 GB، لا تشغّل إعادة بناء embeddings بالتزامن مع حركة مستخدمين
حقيقية. أوقف worker مؤقتًا أو نفّذ المهمة خارج ساعات الذروة. التدريب الكبير
أو GPU inference يحتاج خادم GPU منفصلًا. تبقى snapshots ونتائج التجارب خارج
Git، مع checksum ونسخة model وcommit لكل تجربة.

## 6. التشغيل المستمر

- راقب امتلاء القرص وذاكرة الحاويات وأخطاء 5xx وزمن `/readyz/`.
- راقب انتهاء شهادات TLS رغم التجديد الآلي.
- فعّل نسخًا يومية واختبار استعادة شهريًا.
- لا تحفظ corpus أو نصوص أوراق غير مرخصة في volume عام.
- حدّث صور الأساس والتبعيات عبر Dependabot بعد مرور CI والمراجعة.
- استخدم GitHub Environments عند إضافة نشر آلي، مع موافقة يدوية للإنتاج.
