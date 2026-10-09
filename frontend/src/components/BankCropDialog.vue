<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { quarterTurn } from '../bankCrop.ts'
const props = defineProps<{ files: File[]; open: boolean }>()
const emit = defineEmits<{ (e: 'done', files: File[]): void; (e: 'cancel'): void }>()
const index = ref(0), image = ref<HTMLImageElement | null>(null), url = ref(''), error = ref(''), busy = ref(false)
const ready = ref(false), rotation = ref(0)
const selection = ref<{ x: number; y: number; w: number; h: number } | null>(null)
let start: { x: number; y: number } | null = null, cropped: File[] = []
let generation = 0
function revoke() { if (url.value) URL.revokeObjectURL(url.value); url.value = '' }
function clearImage() { generation++; revoke(); selection.value=null; start=null; ready.value=false; busy.value=false; rotation.value=0; error.value='' }
function nextImage() { clearImage(); const file = props.files[index.value]; if (file) url.value = URL.createObjectURL(file) }
watch(() => props.open, open => { if (open) { index.value = 0; cropped = []; nextImage() } else { clearImage();cropped=[] } })
onBeforeUnmount(clearImage)
function point(event: PointerEvent) { const box = image.value!.getBoundingClientRect(); return { x: Math.max(0, Math.min(1, (event.clientX-box.left)/box.width)), y: Math.max(0, Math.min(1, (event.clientY-box.top)/box.height)) } }
function down(event: PointerEvent) { if (busy.value || !ready.value || !image.value?.naturalWidth) return; start = point(event); (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId); selection.value = null }
function move(event: PointerEvent) { if (busy.value || !ready.value || !start) return; const end = point(event); selection.value = { x: Math.min(start.x,end.x), y: Math.min(start.y,end.y), w: Math.abs(end.x-start.x), h: Math.abs(end.y-start.y) } }
function up(event: PointerEvent) { move(event); start = null }
const boxStyle = computed(() => selection.value ? { left:`${selection.value.x*100}%`,top:`${selection.value.y*100}%`,width:`${selection.value.w*100}%`,height:`${selection.value.h*100}%` } : {})
const pngBlob = (canvas: HTMLCanvasElement) => new Promise<Blob>((resolve,reject)=>canvas.toBlob(blob=>blob?resolve(blob):reject(new Error('PNG_FAILED')),'image/png'))
async function rotate(direction: 1 | -1) {
  const img=image.value
  if(busy.value || !ready.value || !img?.naturalWidth) return
  const current=generation
  busy.value=true;ready.value=false;selection.value=null;start=null;error.value=''
  try {
    const turn=quarterTurn(img.naturalWidth,img.naturalHeight,direction)
    const canvas=document.createElement('canvas');canvas.width=turn.width;canvas.height=turn.height
    const context=canvas.getContext('2d')!;context.setTransform(...turn.transform);context.drawImage(img,0,0)
    const blob=await pngBlob(canvas)
    if(current!==generation || !props.open) return
    revoke();url.value=URL.createObjectURL(blob);rotation.value=(rotation.value+direction*90+360)%360
    await nextTick();await image.value?.decode()
    if(current===generation && props.open) ready.value=true
  } catch { if(current===generation) error.value='旋转未完成，请关闭后重新选择图片。' }
  finally { if(current===generation) busy.value=false }
}
async function confirmCrop() {
  const s = selection.value, img = image.value
  if (busy.value || !ready.value || !s || !img?.naturalWidth) return
  const current=generation
  const w = Math.round(s.w*img.naturalWidth), h = Math.round(s.h*img.naturalHeight)
  if (w < 40 || h < 5 || w/h < 3.5) { error.value = '请选择横向完整卡号一行（宽高比至少3.5），去除姓名、有效期和安全码。'; return }
  busy.value = true
  try {
    const canvas = document.createElement('canvas'); canvas.width=w;canvas.height=h
    canvas.getContext('2d')!.drawImage(img,s.x*img.naturalWidth,s.y*img.naturalHeight,w,h,0,0,w,h)
    const blob = await pngBlob(canvas)
    if(current!==generation || !props.open) return
    const name = props.files[index.value]!.name.replace(/\.[^.]+$/, '') + '-卡号.png'
    cropped.push(new File([blob],name,{type:'image/png'}))
    if (index.value + 1 < props.files.length) { index.value++; nextImage() } else { emit('done',cropped); revoke() }
  } catch { if(current===generation) error.value='无法生成裁剪图片，请另存为 JPG/PNG 后重试。' } finally {if(current===generation) busy.value=false}
}
</script>
<template><el-dialog :model-value="open" title="本地裁剪卡号区域" width="800px" :show-close="!busy" :close-on-click-modal="false" :close-on-press-escape="false" @close="emit('cancel')">
  <el-alert type="info" :closable="false">第 {{ index+1 }} / {{ files.length }} 张。拖动框选完整卡号一行，可先旋转图片。确认后仅将这张裁图提交为新任务，原任务和其他卡片保留。</el-alert>
  <div class="rotation-tools"><el-button :disabled="busy || !ready" @click="rotate(-1)">向左旋转90°</el-button><el-button :disabled="busy || !ready" @click="rotate(1)">向右旋转90°</el-button><span>当前旋转 {{ rotation }}°；旋转后请重新框选。</span></div>
  <div class="crop-stage" @pointerdown.prevent="down" @pointermove.prevent="move" @pointerup.prevent="up" @pointercancel="start = null"><img ref="image" :src="url" draggable="false" alt="仅本地显示的银行卡原图" @load="ready = !busy" @error="ready=false; error = '浏览器不能解码此图片，请先在本地转为 JPG/PNG。'"/><span v-if="selection" class="selection" :style="boxStyle"/></div>
  <el-alert v-if="error" type="error" :closable="false">{{ error }}</el-alert>
  <template #footer><el-button :disabled="busy" @click="emit('cancel')">取消（不上传）</el-button><el-button type="primary" :disabled="!selection || !ready || busy" :loading="busy" @click="confirmCrop">{{ index+1 === files.length ? '确认裁图并上传' : '确认并裁下一张' }}</el-button></template>
</el-dialog></template>
<style scoped>.crop-stage{position:relative;display:table;max-width:100%;margin:14px auto;touch-action:none;user-select:none}.crop-stage img{display:block;max-width:100%;max-height:60vh;pointer-events:none}.selection{position:absolute;pointer-events:none;border:2px solid #2c7be5;background:#2c7be530;box-sizing:border-box}</style>
