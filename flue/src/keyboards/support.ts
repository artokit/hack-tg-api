import type { InlineKeyboardMarkup } from 'grammy/types';

export function get_support_keyboard(): InlineKeyboardMarkup {
  return {
    inline_keyboard: [[{ text: 'Обратиться к специалисту', callback_data: 'end_ask' }]],
  };
}
