---
id: demo-xss
title: "<img src=x onerror=alert(1)>口試須知"
source: 示範用假資料，內含 HTML 字串，用來檢查畫面不會執行它
version_date: 2025-10-01
public: true
---
注意事項：<script>alert("body-xss")</script> 請於口試前確認所有文件。
<b>粗體標記</b>與 &lt;i&gt; 實體字元都要原樣顯示。
<script>alert("evil")</script><img src=x onerror=alert(1)> 學期
