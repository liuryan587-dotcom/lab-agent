<template>
  <div>
    <el-dialog
      :model-value="visible"
      title="预约"
      width="450"
      @open="formRef.resetFields()"
      @close="emit('update:visible', false)"
    >
      <el-form
        ref="formRef"
        :rules="rules"
        :model="form"
        label-width="80px"
        style="width: 100%; padding-right: 30px; padding-top: 16px"
      >
        <el-form-item label="实验室">
          <el-input :model-value="labName" disabled />
        </el-form-item>
        <el-form-item label="设备">
          <el-input :model-value="equipmentName" disabled />
        </el-form-item>
        <el-form-item label="预约日期" prop="date"
          ><el-date-picker
            v-model="form.date"
            type="date"
            format="YYYY-MM-DD"
            value-format="YYYY-MM-DD"
            placeholder="请选择日期"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="可用时段">
          <div class="slot-box">
            <span v-if="slotsLoading" class="slot-hint">加载中…</span>
            <span v-else-if="!slots.length" class="slot-hint">该日期暂无可约时段</span>
            <template v-else>
              <el-tag
                v-for="label in slots"
                :key="label"
                class="slot-tag"
                :type="form.startTime === label ? 'primary' : 'info'"
                :effect="form.startTime === label ? 'dark' : 'plain'"
                @click="pickSlot(label)"
              >
                {{ label }}
              </el-tag>
              <span class="slot-hint slot-count">共 {{ slots.length }} 个</span>
            </template>
          </div>
        </el-form-item>
        <el-form-item label="开始时间" prop="startTime"
          ><el-time-picker
            v-model="form.startTime"
            format="HH:mm"
            value-format="HH:mm"
            placeholder="请选择开始时间"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="结束时间" prop="endTime"
          ><el-time-picker
            v-model="form.endTime"
            format="HH:mm"
            value-format="HH:mm"
            placeholder="请选择结束时间"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="备注">
          <el-input type="textarea" v-model="form.remark" placeholder="请输入备注信息" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="emit('update:visible', false)">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { createReservationApi, getStartsApi } from '@/api/reservation'
import { ElMessage } from 'element-plus'
import { ref, reactive, watch } from 'vue'
const props = defineProps({
  visible: Boolean,
  labId: Number,
  labName: String,
  equipmentId: Number,
  equipmentName: String
})
const submitting = ref(false)
const emit = defineEmits(['update:visible'])
const formRef = ref()
const form = reactive({
  date: '',
  startTime: '09:00',
  endTime: '18:00',
  remark: ''
})
const rules = {
  date: [{ required: true, message: '请选择预约日期', trigger: 'change' }],
  startTime: [{ required: true, message: '请选择开始时间', trigger: 'change' }],
  endTime: [{ required: true, message: '请选择结束时间', trigger: 'change' }]
}

// 单次预约时长（分钟）。查可用时段和回填结束时间都用它，避免两处写死不同的值。
const SLOT_MINUTES = 60

const slots = ref([])
const slotsLoading = ref(false)

const toMinutes = (hhmm) => {
  const [h, m] = hhmm.split(':').map(Number)
  return h * 60 + m
}

const toLabel = (minutes) => {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

const loadSlots = async (day) => {
  if (!day) {
    slots.value = []
    return
  }
  slotsLoading.value = true
  try {
    const res = await getStartsApi({
      lab_id: props.labId,
      day,
      slot_duration: SLOT_MINUTES
    })
    slots.value = res.data?.labels || []
  } catch {
    // 请求失败时拦截器已经弹过提示，这里只清空，别让弹窗永远停在"加载中"
    slots.value = []
  } finally {
    slotsLoading.value = false
  }
}

const pickSlot = (label) => {
  form.startTime = label
  form.endTime = toLabel(toMinutes(label) + SLOT_MINUTES)
}

watch(() => form.date, loadSlots)

const handleSubmit = async () => {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    const res = await createReservationApi({
      lab_id: props.labId,
      equipment_id: props.equipmentId,
      date: form.date,
      start_time: form.startTime,
      end_time: form.endTime,
      remark: form.remark
    })

    if (res.code === 200) {
      ElMessage.success('预约已提交，请等待审核')
      emit('update:visible', false)
    }
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.slot-box {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  min-height: 24px;
}

.slot-tag {
  margin: 0;
  cursor: pointer;
}

.slot-hint {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.slot-count {
  margin-left: 4px;
}
</style>
