# fgo dataset stats

| game | characters | outfits (base+skins) | clips | usable clips | usable duration | female / male / other / unknown |
|---|---|---|---|---|---|---|
| fgo | 471 | 620 | 45829 | 31677 | 89.59 h | 61% / 35% / 0% / 4% |

## Clips by category_norm

| category_norm | usable | excluded |
|---|---|---|
| battle | 12709 | 13356 |
| bond | 3194 | 144 |
| daily | 8842 | 428 |
| other | 3143 | 151 |
| system | 3789 | 73 |

Text filled by Whisper ASR (text_source=asr): 6050. Usable clips flagged is_legacy (pre-remake recording): 6.

## Usable clips per character

min 0, p25 44, median 57, p75 85, max 197

| usable clips per character | # characters |
|---|---|
| 0 | 2 |
| 1–9 | 3 |
| 10–29 | 7 |
| 30–59 | 239 |
| 60–99 | 141 |
| 100+ | 79 |

## Exclusion reasons

| reason | clips flagged | sole reason |
|---|---|---|
| battle_shout | 12841 | 12432 |
| duplicate_audio | 1455 | 1124 |
| no_audio_source | 144 | 80 |
| non_japanese | 113 | 71 |
| no_text | 43 | 8 |
| not_downloaded | 2 | 2 |

Duration flags (not excluded): short (<1 s) 6087, long (>15 s) 7886; of these, usable: short 803, long 7485.

## name_ja shared by several characters (kept separate)

アルトリア・ペンドラゴン, アルトリア・ペンドラゴン〔オルタ〕, ネロ・クラウディウス, ジル・ド・レェ, ギルガメッシュ, クー・フーリン, エリザベート・バートリー, メドゥーサ, 牛若丸, マリー・アントワネット, マルタ, カーミラ, ランスロット, 坂田金時, 清姫, ジャンヌ・ダルク, 玉藻の前, アン・ボニー＆メアリー・リード, 沖田総司, 織田信長, スカサハ, ディルムッド・オディナ, モードレッド, フランケンシュタイン, ブリュンヒルデ, 両儀式, アストルフォ, 女王メイヴ, エレナ・ブラヴァツキー, 李書文, ジャンヌ・ダルク〔オルタ〕, 酒呑童子, 源頼光, 茨木童子, ニトクリス, レオナルド・ダ・ヴィンチ, イリヤスフィール・フォン・アインツベルン, クロエ・フォン・アインツベルン, イシュタル, 宮本武蔵, ジェームズ・モリアーティ, パッションリップ, ＢＢ, 殺生院キアラ, 武則天, 巴御前, 刑部姫, エレシュキガル, 葛飾北斎, 沖田総司〔オルタ〕, 坂本龍馬, スカサハ＝スカディ, 虞美人, 紅閻魔, 美遊・エーデルフェルト, 紫式部, キングプロテア, カーマ, ガレス, シャルロット・コルデー, 清少納言, カイニス, 宇津見エリセ, アルトリア・キャスター, 伊吹童子, メリュジーヌ, ハベトロット, ジャック・ド・モレー, ドブルイニャ・ニキチッチ, クリームヒルト, 徐福, 呼延灼, テノチティトラン, ラーヴァ／ティアマト, 岸波白野, ビショーネ, 小野小町, リリス, グレイ・リリィ

## Characters with missing fields

| char_uid | name_ja | missing |
|---|---|---|
| fgo:10 | シュヴァリエ・デオン | gender |
| fgo:94 | アストルフォ | gender |
| fgo:143 | エルキドゥ | gender |
| fgo:229 | 始皇帝 | gender |
| fgo:250 | 魔王信長 | gender |
| fgo:270 | アストルフォ | gender |
| fgo:278 | ディオスクロイ | gender |
| fgo:279 | カイニス | gender |
| fgo:280 | ロムルス＝クィリヌス | gender |
| fgo:297 | 蘆屋道満 | gender |
| fgo:303 | 平景清 | gender |
| fgo:304 | 鬼一法眼 | gender |
| fgo:317 | 沖田総司〔オルタ〕 | gender |
| fgo:322 | カイニス | gender |
| fgo:328 | 謎の蘭丸X | gender |
| fgo:380 | 果心居士 | gender |
| fgo:393 | ワンジナ | gender |
| fgo:395 | 杉谷善住坊 | gender |
| fgo:402 | ヤマトタケル | gender |
| fgo:416 | ひびき＆千鍵 | gender |
| fgo:442 | インドラ | gender |
| fgo:482 | ダイダロス | usable_clips |
| fgo:483 | タマモアリア | usable_clips |
