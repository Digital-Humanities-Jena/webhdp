import { computed, defineComponent } from 'vue'

export const RouterLinkStub = defineComponent({
  name: 'RouterLink',
  props: {
    to: {
      type: [String, Object],
      required: true,
    },
    custom: {
      type: Boolean,
      default: false,
    },
  },
  setup(props) {
    const href = computed(() => {
      if (typeof props.to === 'string') {
        return props.to
      }
      if (props.to?.path) {
        return props.to.path
      }
      if (props.to?.name) {
        return String(props.to.name)
      }
      return '#'
    })

    const navigate = (event) => {
      event?.preventDefault?.()
    }

    return {
      href,
      navigate,
    }
  },
  template: `
    <a :href="href" @click="navigate">
      <slot v-if="!custom" />
      <slot v-else :href="href" :navigate="navigate" :isActive="false" />
    </a>
  `,
})
